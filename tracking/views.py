# ======================================================
# BULK LOCATION UPLOAD (Offline Sync)
# ======================================================
import logging
import math
from datetime import timedelta

logger = logging.getLogger(__name__)

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404
from django.db.models import Subquery, OuterRef

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from accounts.models import EmployeeProfile
from utils.photo_urls import build_profile_photo_url
from .models import WorkDay, AvailabilityEvent, LocationLog, EmployeeDailySummary
from .selectors import get_last_known_location
from .status_utils import build_admin_tracking_row
from .workday_utils import (
    WORKDAY_EXPIRED_MESSAGE,
    expire_old_workdays,
    expire_overlong_workdays_for_user,
    is_workday_within_duration,
)
from .serializers import (
    LocationLogCreateSerializer,
    LocationLogSerializer,
    BulkLocationPushSerializer,
    HeartbeatSerializer,
)
from utils.response import api_response, not_found_response, success_response
from utils.schema import SIMPLE_SUCCESS, PAGINATION_PARAMS, error_schema
from .route_utils import (
    build_admin_route_data,
    build_route_points,
    get_route_queryset,
)
from mobile_api.device_session import DeviceSessionRequiredMixin


@extend_schema(
    tags=["Tracking"],
    summary="Bulk upload location logs (offline sync)",
    description="Accepts a list of location logs for offline-synced GPS data. Returns created IDs and any errors.",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "locations": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
        }
    },
    responses={201: SIMPLE_SUCCESS},
)
class BulkLocationUploadAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Accept either:
        # 1) {"locations": [...]} or 2) [...] (raw array payload)
        if isinstance(request.data, list):
            locations_data = request.data
        elif isinstance(request.data, dict):
            locations_data = request.data.get("locations", [])
        else:
            return api_response(
                success=False,
                message="Invalid payload format",
                data={"errors": [{"detail": "Expected list or object payload"}]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(locations_data, list):
            return api_response(
                success=False,
                message="Invalid locations format",
                data={"errors": [{"locations": ["Must be a list"]}]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expire_overlong_workdays_for_user(request.user)
        if not WorkDay.objects.filter(user=request.user, is_active=True).exists():
            return api_response(
                success=False,
                message=WORKDAY_EXPIRED_MESSAGE,
                data={"errors": [{"detail": "No active workday"}]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        errors = []
        for ldata in locations_data:
            serializer = LocationLogCreateSerializer(
                data=ldata, context={"request": request}
            )
            if serializer.is_valid():
                loc = serializer.save()
                created.append(loc.id)
            else:
                errors.append(serializer.errors)
        return api_response(
            success=len(errors) == 0,
            message="Bulk locations upload complete",
            data={"created": created, "errors": errors},
            status=(
                status.HTTP_201_CREATED
                if len(errors) == 0
                else status.HTTP_207_MULTI_STATUS
            ),
        )


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
HEARTBEAT_STALE_MINUTES = 5
HEARTBEAT_STOPPED_MINUTES = 15
GPS_JUMP_KM = 5
MAX_BULK_POINTS = 500


def _employee_location_tuple(user_id, last_locations, active_workdays, now):
    """Latest lat/lng + last_seen from DB subquery, Redis live cache, or workday start."""
    loc = last_locations.get(user_id)
    if loc:
        recorded = loc.get("recorded_at") if isinstance(loc, dict) else loc.recorded_at
        lat = loc.get("latitude") if isinstance(loc, dict) else loc.latitude
        lng = loc.get("longitude") if isinstance(loc, dict) else loc.longitude
        last_seen = recorded.isoformat() if hasattr(recorded, "isoformat") else str(recorded)
        return float(lat), float(lng), last_seen

    live = get_last_known_location(user_id)
    if live and live.get("latitude") is not None:
        recorded = live.get("recorded_at")
        last_seen = (
            recorded.isoformat() if hasattr(recorded, "isoformat") else str(recorded)
        )
        return float(live["latitude"]), float(live["longitude"]), last_seen

    workday = active_workdays.get(user_id)
    if workday and workday.latitude is not None and workday.longitude is not None:
        last_seen = workday.last_heartbeat.isoformat() if workday.last_heartbeat else None
        return float(workday.latitude), float(workday.longitude), last_seen
    return None, None, None


# ──────────────────────────────────────────────
# Utility: Haversine distance (KM)
# ──────────────────────────────────────────────
def distance_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _format_duration(delta):
    total_seconds = max(int(delta.total_seconds()), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def _tracking_health(workday, now):
    """Return OK / STALE / STOPPED for an active workday."""
    if not is_workday_within_duration(workday, now):
        return "STOPPED"
    hb = workday.last_heartbeat
    if not hb:
        return "STOPPED"
    diff = (now - hb).total_seconds() / 60
    if diff <= HEARTBEAT_STALE_MINUTES:
        return "OK"
    if diff <= HEARTBEAT_STOPPED_MINUTES:
        return "STALE"
    return "STOPPED"


def _compute_distance_km(user_id, date):
    """Compute total route distance for a user on a given date."""
    points = list(
        LocationLog.objects.filter(
            user_id=user_id,
            recorded_at__date=date,
        )
        .order_by("recorded_at")
        .values_list("latitude", "longitude")
    )
    total = 0.0
    for i in range(1, len(points)):
        total += distance_km(
            float(points[i - 1][0]),
            float(points[i - 1][1]),
            float(points[i][0]),
            float(points[i][1]),
        )
    return round(total, 2)


# ──────────────────────────────────────────────
# START WORKDAY
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Start work day",
    description="Marks the start of a field employee's work day. Employee access only.",
    request=None,
    responses={201: SIMPLE_SUCCESS, 400: error_schema("WorkdayAlreadyStarted")},
)
class StartWorkDayAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.is_staff:
            return Response({"detail": "Admins cannot start workday"}, status=403)

        profile = EmployeeProfile.objects.filter(user=request.user).first()
        if profile and not profile.is_active_employee:
            return Response({"detail": "Inactive employee"}, status=403)

        expire_overlong_workdays_for_user(request.user)

        if WorkDay.objects.filter(user=request.user, is_active=True).exists():
            return Response({"detail": "Workday already started"}, status=400)

        now = timezone.now()
        workday_kwargs = {
            "user": request.user,
            "date": now.date(),
            "start_time": now,
            "is_active": True,
            "last_heartbeat": now,
        }
        lat = request.data.get("latitude")
        lng = request.data.get("longitude")
        if lat not in (None, "") and lng not in (None, ""):
            try:
                workday_kwargs["latitude"] = float(lat)
                workday_kwargs["longitude"] = float(lng)
            except (TypeError, ValueError):
                pass
        workday = WorkDay.objects.create(**workday_kwargs)
        logger.info(
            "WorkdayStart user_id=%s workday_id=%s start_time=%s",
            request.user.pk,
            workday.pk,
            workday.start_time,
        )
        return Response({"message": "Workday started", "workday_id": workday.id}, status=201)


# ──────────────────────────────────────────────
# END WORKDAY
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="End work day",
    description="Ends the current active work day for the employee.",
    request=None,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("NoActiveWorkday")},
)
class EndWorkDayAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.is_staff:
            return Response({"detail": "Admins cannot end workday"}, status=403)

        expire_overlong_workdays_for_user(request.user)

        workdays = WorkDay.objects.filter(user=request.user, is_active=True)
        if not workdays.exists():
            return Response({"detail": "No active workday"}, status=400)

        from .workday_utils import clear_live_tracking_for_user

        now = timezone.now()
        count = workdays.count()
        workdays.update(end_time=now, is_active=False, auto_ended=False)
        clear_live_tracking_for_user(request.user.pk)
        return Response({"message": "Workday ended", "ended_count": count}, status=200)


# ──────────────────────────────────────────────
# HEARTBEAT
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Send heartbeat",
    description="Updates the last heartbeat timestamp for the employee's active work day. Used to detect online/offline status.",
    request=None,
    responses={200: SIMPLE_SUCCESS},
)
class HeartbeatAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.is_staff:
            return Response({"detail": "Admin heartbeat not allowed"}, status=403)

        expire_overlong_workdays_for_user(request.user)

        serializer = HeartbeatSerializer(
            data=request.data if request.data else {"gps_enabled": True},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "Heartbeat received"}, status=200)


# ──────────────────────────────────────────────
# PUSH LOCATION (single point)
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Push single location point",
    description="Pushes a single GPS location log for the current employee.",
    request=BulkLocationPushSerializer,
    responses={201: SIMPLE_SUCCESS, 400: error_schema("LocationPushError")},
)
class PushLocationAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.is_staff:
            return Response({"detail": "Admin cannot push location"}, status=403)

        expire_overlong_workdays_for_user(user)

        serializer = LocationLogCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        profile = EmployeeProfile.objects.filter(user=user).first()
        if profile and not profile.is_active_employee:
            return Response({"detail": "Inactive employee"}, status=403)

        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        if not workday:
            return Response(
                {
                    "detail": WORKDAY_EXPIRED_MESSAGE
                },
                status=400,
            )

        lat = float(serializer.validated_data["latitude"])
        lng = float(serializer.validated_data["longitude"])
        accuracy = float(serializer.validated_data.get("accuracy") or 999)

        is_suspicious = False

        # Flag low accuracy
        if accuracy > 50:
            is_suspicious = True

        # Flag GPS jump
        last_point = (
            LocationLog.objects.filter(user=user, workday=workday)
            .order_by("-recorded_at")
            .first()
        )
        if last_point:
            jump = distance_km(
                float(last_point.latitude),
                float(last_point.longitude),
                lat,
                lng,
            )
            if jump > GPS_JUMP_KM:
                is_suspicious = True

        location = serializer.save()
        if is_suspicious:
            location.is_suspicious = True
            location.save(update_fields=["is_suspicious"])

        logger.info(
            "LocationPush employee_id=%s workday_id=%s lat=%s lng=%s heartbeat_updated=1",
            user.pk,
            workday.pk,
            lat,
            lng,
        )

        out = LocationLogSerializer(location, context={"request": request}).data
        return Response({"message": "Location saved", "location": out}, status=201)


# ──────────────────────────────────────────────
# BULK PUSH LOCATIONS (offline batch)
# POST /api/tracking/location/bulk/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Bulk push location points",
    description="Batch-upload up to 500 GPS location points. Used for offline sync. Validates and filters suspicious points.",
    responses={201: SIMPLE_SUCCESS, 207: SIMPLE_SUCCESS},
)
class BulkPushLocationAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.is_staff:
            return Response({"detail": "Admin cannot push location"}, status=403)

        expire_overlong_workdays_for_user(user)

        profile = EmployeeProfile.objects.filter(user=user).first()
        if profile and not profile.is_active_employee:
            return Response({"detail": "Inactive employee"}, status=403)

        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        if not workday:
            return Response(
                {
                    "detail": WORKDAY_EXPIRED_MESSAGE
                },
                status=400,
            )

        serializer = BulkLocationPushSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        points = serializer.validated_data["locations"]
        if len(points) > MAX_BULK_POINTS:
            return Response(
                {"detail": f"Max {MAX_BULK_POINTS} points per request"},
                status=400,
            )

        device_model = serializer.validated_data.get("device_model")
        app_version = serializer.validated_data.get("app_version")

        def _point_time(pt):
            return pt.get("captured_at") or pt.get("recorded_at") or timezone.now()

        # Sort by device timestamp so jump detection is sequential
        points.sort(key=_point_time)

        # Get last saved point for jump detection
        prev = (
            LocationLog.objects.filter(user=user, workday=workday)
            .order_by("-recorded_at")
            .values_list("latitude", "longitude")
            .first()
        )
        prev_lat = float(prev[0]) if prev else None
        prev_lng = float(prev[1]) if prev else None

        objects_to_create = []
        saved = 0
        suspicious = 0

        for pt in points:
            lat = float(pt["latitude"])
            lng = float(pt["longitude"])
            accuracy = float(pt.get("accuracy") or 999)
            is_sus = False

            if accuracy > 50:
                is_sus = True

            if prev_lat is not None:
                jump = distance_km(prev_lat, prev_lng, lat, lng)
                if jump > GPS_JUMP_KM:
                    is_sus = True

            recorded_at = _point_time(pt)
            objects_to_create.append(
                LocationLog(
                    user=user,
                    workday=workday,
                    latitude=pt["latitude"],
                    longitude=pt["longitude"],
                    accuracy=pt.get("accuracy"),
                    speed=pt.get("speed"),
                    heading=pt.get("heading"),
                    battery_level=pt.get("battery_level"),
                    network_type=pt.get("network_type"),
                    device_model=device_model,
                    app_version=app_version,
                    recorded_at=recorded_at,
                    is_suspicious=is_sus,
                )
            )
            if is_sus:
                suspicious += 1
            saved += 1
            prev_lat, prev_lng = lat, lng

        LocationLog.objects.bulk_create(objects_to_create)

        if points:
            from .services import refresh_workday_live_state

            latest = points[-1]
            refresh_workday_live_state(
                user=user,
                workday=workday,
                latitude=float(latest["latitude"]),
                longitude=float(latest["longitude"]),
                accuracy=float(latest["accuracy"]) if latest.get("accuracy") is not None else None,
                battery_level=latest.get("battery_level"),
                recorded_at=latest["recorded_at"],
            )
            logger.info(
                "BulkLocationPush employee_id=%s workday_id=%s lat=%s lng=%s heartbeat_updated=1 saved=%s",
                user.pk,
                workday.pk,
                latest["latitude"],
                latest["longitude"],
                saved,
            )

        return Response(
            {
                "message": f"{saved} locations saved",
                "saved": saved,
                "suspicious": suspicious,
            },
            status=201,
        )


# ══════════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════════


# ──────────────────────────────────────────────
# ADMIN: DASHBOARD STATS
# GET /api/tracking/admin/dashboard-stats/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: tracking dashboard stats",
    description="Returns real-time tracking statistics: total employees, online count, on-field count, GPS health.",
    responses={200: SIMPLE_SUCCESS},
)
class AdminTrackingDashboardStatsAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        expire_old_workdays()
        now = timezone.now()
        heartbeat_threshold = now - timedelta(minutes=HEARTBEAT_STALE_MINUTES)

        total_employees = EmployeeProfile.objects.filter(
            is_active_employee=True,
        ).count()

        active_wds = list(
            WorkDay.objects.filter(is_active=True).only(
                "start_time", "last_heartbeat", "is_active", "user_id"
            )
        )
        working_now = sum(1 for wd in active_wds if is_workday_within_duration(wd, now))
        online = sum(
            1
            for wd in active_wds
            if is_workday_within_duration(wd, now)
            and wd.last_heartbeat
            and wd.last_heartbeat >= heartbeat_threshold
        )

        offline = total_employees - online

        gps_issues = AvailabilityEvent.objects.filter(
            event_type="GPS_OFF",
            end_time__isnull=True,
        ).count()

        return Response(
            {
                "total_employees": total_employees,
                "working_now": working_now,
                "online": online,
                "offline": offline,
                "gps_issues": gps_issues,
            }
        )


# ──────────────────────────────────────────────
# ADMIN: LIVE STATUS
# GET /api/tracking/admin/status/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee tracking status list",
    description="Returns paginated list of all employees with their current tracking status, GPS health, and last location.",
    parameters=PAGINATION_PARAMS,
    responses={200: SIMPLE_SUCCESS},
)
class AdminTrackingStatusAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        expire_old_workdays()
        now = timezone.now()
        heartbeat_threshold = now - timedelta(minutes=HEARTBEAT_STALE_MINUTES)

        # 1. All active employees with village->district chain
        employees = EmployeeProfile.objects.filter(
            is_active_employee=True
        ).select_related("user", "village", "village__district")

        # 2. Active workdays keyed by user_id (single query)
        active_workdays = {
            wd.user_id: wd
            for wd in WorkDay.objects.filter(is_active=True).select_related("user")
            if is_workday_within_duration(wd, now=now)
        }
        working_user_ids = list(active_workdays.keys())

        # 3. Latest LocationLog per working user (single subquery)
        last_locations = {}
        if working_user_ids:
            latest_loc_subq = (
                LocationLog.objects.filter(user_id=OuterRef("user_id"))
                .order_by("-recorded_at")
                .values("id")[:1]
            )
            latest_locs_qs = LocationLog.objects.filter(
                user_id__in=working_user_ids,
                id=Subquery(latest_loc_subq),
            ).values("user_id", "latitude", "longitude", "recorded_at")
            last_locations = {loc["user_id"]: loc for loc in latest_locs_qs}

        # 4. Active GPS_OFF events -> set of user_ids (single query)
        gps_off_user_ids = set(
            AvailabilityEvent.objects.filter(
                user_id__in=working_user_ids,
                event_type="GPS_OFF",
                end_time__isnull=True,
            ).values_list("user_id", flat=True)
        )

        data = []
        for emp in employees:
            uid = emp.user_id
            workday = active_workdays.get(uid)
            loc = last_locations.get(uid)
            try:
                row = build_admin_tracking_row(
                    emp=emp,
                    user=emp.user,
                    workday=workday,
                    last_location=loc,
                    gps_off=uid in gps_off_user_ids,
                    now=now,
                    request=request,
                )
            except Exception:
                logger.exception("Failed to build tracking row user_id=%s", uid)
                row = {
                    "user_id": uid,
                    "employee_id": emp.employee_id,
                    "employee_name": emp.user.username or emp.employee_id,
                    "work_status": "NOT_WORKING",
                    "connection": "OFFLINE",
                    "gps_status": "GPS_OFF",
                    "movement_status": "stopped",
                    "tracking_health": "STOPPED",
                    "active_workday": False,
                }
            data.append(row)

        logger.info("AdminTrackingStatus map_rows=%s online=%s", len(data), sum(1 for r in data if r["connection"] == "ONLINE"))
        return Response(data)


# ──────────────────────────────────────────────
# ADMIN: EMPLOYEES GeoJSON
# GET /api/tracking/admin/geo/employees/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employees GeoJSON",
    description="Returns GeoJSON Feature Collection of all employees with their last known GPS location.",
    responses={200: SIMPLE_SUCCESS},
)
class AdminEmployeesGeoJSONAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        expire_old_workdays()
        now = timezone.now()
        heartbeat_threshold = now - timedelta(minutes=HEARTBEAT_STALE_MINUTES)

        employees = EmployeeProfile.objects.filter(
            is_active_employee=True
        ).select_related("user")

        active_workdays = {
            wd.user_id: wd
            for wd in WorkDay.objects.filter(is_active=True).select_related("user")
            if is_workday_within_duration(wd, now=now)
        }
        working_user_ids = list(active_workdays.keys())

        last_locations = {}
        if working_user_ids:
            latest_loc_subq = (
                LocationLog.objects.filter(user_id=OuterRef("user_id"))
                .order_by("-recorded_at")
                .values("id")[:1]
            )
            for loc in LocationLog.objects.filter(
                user_id__in=working_user_ids,
                id=Subquery(latest_loc_subq),
            ):
                last_locations[loc.user_id] = loc

        gps_off_user_ids = set(
            AvailabilityEvent.objects.filter(
                user_id__in=working_user_ids,
                event_type="GPS_OFF",
                end_time__isnull=True,
            ).values_list("user_id", flat=True)
        )

        features = []
        for emp in employees:
            uid = emp.user_id
            user = emp.user
            workday = active_workdays.get(uid)

            geo_photo_updated = emp.profile_photo_updated_at
            props = {
                "employee_id": emp.employee_id,
                "username": user.username,
                "employee_name": user.username or emp.employee_id,
                "phone": emp.phone,
                "profile_photo_url": build_profile_photo_url(request, emp.profile_photo),
                "profile_photo_updated_at": (
                    geo_photo_updated.isoformat() if geo_photo_updated else None
                ),
                "work_status": "NOT_WORKING",
                "connection": "OFFLINE",
                "gps_status": "GPS_OFF",
                "tracking_health": "STOPPED",
            }
            geom = None

            if workday and is_workday_within_duration(workday, now):
                props["work_status"] = "WORKING"
                props["tracking_health"] = _tracking_health(workday, now)

                loc = last_locations.get(uid)
                loc_recent = (
                    loc
                    and loc.recorded_at
                    and loc.recorded_at >= heartbeat_threshold
                )
                if (workday.last_heartbeat and workday.last_heartbeat >= heartbeat_threshold) or loc_recent:
                    props["connection"] = "ONLINE"

                props["gps_status"] = "GPS_OFF" if uid in gps_off_user_ids else "GPS_ON"

                lat, lng, last_seen = _employee_location_tuple(
                    uid, last_locations, active_workdays, now
                )
                if lat is not None:
                    geom = {"type": "Point", "coordinates": [lng, lat]}
                    props["latitude"] = lat
                    props["longitude"] = lng
                    props["last_seen"] = last_seen
                    props["user_id"] = uid

            features.append({"type": "Feature", "properties": props, "geometry": geom})

        with_geom = sum(1 for f in features if f.get("geometry"))
        logger.info(
            "AdminEmployeesGeoJSON features=%s with_geometry=%s",
            len(features),
            with_geom,
        )
        return Response({"type": "FeatureCollection", "features": features})


# ──────────────────────────────────────────────
# ADMIN: EMPLOYEE ROUTE GeoJSON
# GET /api/tracking/admin/geo/routes/<user_id>/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee route GeoJSON",
    description="Returns GeoJSON LineString of a specific employee's GPS route for a given date.",
    parameters=[
        OpenApiParameter("date", OpenApiTypes.DATE, description="Date (YYYY-MM-DD)")
    ],
    responses={200: SIMPLE_SUCCESS},
)
class AdminEmployeeRouteGeoJSONAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        date_str = request.GET.get("date")
        target_date = parse_date(date_str) if date_str else timezone.now().date()

        coords = list(
            LocationLog.objects.filter(
                user_id=user_id,
                recorded_at__date=target_date,
            )
            .order_by("recorded_at")
            .values_list("longitude", "latitude")
        )

        geometry = None
        if coords:
            geometry = {
                "type": "LineString",
                "coordinates": [[float(lng), float(lat)] for lng, lat in coords],
            }

        return Response(
            {
                "type": "Feature",
                "properties": {"user_id": user_id, "date": str(target_date)},
                "geometry": geometry,
            }
        )


# ──────────────────────────────────────────────
# ADMIN: EMPLOYEE LAST LOCATION
# GET /api/tracking/admin/geo/last_location/<user_id>/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee last location",
    description="Returns the most recent GPS location log for a specific employee.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("TrackingNotFound")},
)
class AdminEmployeeLastLocationAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        last = (
            LocationLog.objects.filter(user_id=user_id).order_by("-recorded_at").first()
        )
        if not last:
            return Response({"detail": "No location found"}, status=404)
        return Response(LocationLogSerializer(last, context={"request": request}).data)


# ══════════════════════════════════════════════
# EMPLOYEE ENDPOINTS
# ══════════════════════════════════════════════


# ──────────────────────────────────────────────
# EMPLOYEE: CURRENT WORKDAY + LAST LOCATION
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Current workday status",
    description="Returns the active workday details and last known location for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("NoActiveWorkday")},
)
class CurrentWorkdayAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        expire_overlong_workdays_for_user(request.user)
        workday = WorkDay.objects.filter(user=request.user, is_active=True).first()
        if not workday:
            return Response(
                {
                    "detail": WORKDAY_EXPIRED_MESSAGE,
                    "code": "workday_expired",
                },
                status=404,
            )

        last_loc = (
            LocationLog.objects.filter(user=request.user, workday=workday)
            .order_by("-recorded_at")
            .first()
        )
        data = {
            "workday_id": workday.id,
            "date": workday.date,
            "start_time": workday.start_time,
            "end_time": workday.end_time,
            "is_active": workday.is_active,
            "auto_ended": workday.auto_ended,
            "last_heartbeat": workday.last_heartbeat,
            "last_location": (
                LocationLogSerializer(last_loc, context={"request": request}).data
                if last_loc
                else None
            ),
        }
        return Response(data)


# ──────────────────────────────────────────────
# EMPLOYEE: WORKDAY LOCATIONS (paginated)
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Workday GPS locations",
    description="Returns paginated GPS location logs for a specific workday.",
    parameters=PAGINATION_PARAMS,
    responses={200: LocationLogSerializer(many=True)},
)
class WorkdayLocationsAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workday_id):
        workday = get_object_or_404(WorkDay, id=workday_id)
        if workday.user != request.user and not request.user.is_staff:
            return Response({"detail": "Not authorized"}, status=403)

        qs = LocationLog.objects.filter(workday=workday).order_by("recorded_at")
        paginator = PageNumberPagination()
        paginator.page_size = min(int(request.GET.get("page_size", 100)), 500)
        page = paginator.paginate_queryset(qs, request)
        serializer = LocationLogSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)


# ──────────────────────────────────────────────
# EMPLOYEE: WORKDAY HISTORY
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Workday history",
    description="Returns the last 90 workdays for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS},
)
class WorkdayHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        expire_overlong_workdays_for_user(request.user)

        if request.user.is_staff:
            qs = (
                WorkDay.objects.select_related("user")
                .order_by("-start_time")[:90]
            )
        else:
            qs = WorkDay.objects.filter(user=request.user).order_by("-date")[:90]

        data = []
        for w in qs:
            row = {
                "id": w.id,
                "workday_id": w.id,
                "date": w.date,
                "start_time": w.start_time,
                "end_time": w.end_time,
                "is_active": w.is_active,
                "auto_ended": w.auto_ended,
                "status": "active" if w.is_active else "completed",
                "last_heartbeat": w.last_heartbeat,
            }
            if request.user.is_staff:
                row["employee"] = {
                    "id": w.user_id,
                    "username": w.user.username,
                    "first_name": w.user.first_name,
                }
            data.append(row)
        return Response(data)


# ──────────────────────────────────────────────
# EMPLOYEE: AVAILABILITY EVENTS
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Availability events",
    description="Returns the last 200 GPS availability events (GPS on/off, etc.) for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS},
)
class AvailabilityEventsAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AvailabilityEvent.objects.filter(user=request.user).order_by(
            "-start_time"
        )[:200]
        data = [
            {
                "event_type": e.event_type,
                "start_time": e.start_time,
                "end_time": e.end_time,
            }
            for e in qs
        ]
        return Response(data)


# ══════════════════════════════════════════════
# ADMIN: PER-EMPLOYEE DETAIL ENDPOINTS
# ══════════════════════════════════════════════


# ──────────────────────────────────────────────
# ADMIN: EMPLOYEE ROUTE
# GET /api/tracking/admin/employee/<id>/route/?date=YYYY-MM-DD
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee GPS route",
    description="Returns chronological route points and total distance for an employee on a given date.",
    parameters=[
        OpenApiParameter("date", OpenApiTypes.DATE, description="Date (YYYY-MM-DD)")
    ],
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeRouteAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        try:
            emp = EmployeeProfile.objects.get(
                user_id=user_id,
                is_active_employee=True,
            )
        except EmployeeProfile.DoesNotExist:
            logger.info("AdminRoute employee not found or inactive user_id=%s", user_id)
            return not_found_response("Employee not found")

        date_str = request.GET.get("date")
        target_date = parse_date(date_str) if date_str else timezone.now().date()

        try:
            qs = get_route_queryset(user_id=user_id, target_date=target_date)
            route = build_route_points(qs)
            data = build_admin_route_data(
                employee_id=emp.employee_id,
                user_id=user_id,
                target_date=target_date,
                route=route,
            )
        except Exception:
            logger.exception(
                "AdminRoute failed user_id=%s date=%s", user_id, target_date
            )
            data = build_admin_route_data(
                employee_id=emp.employee_id,
                user_id=user_id,
                target_date=target_date,
                route=[],
            )

        logger.info(
            "AdminRoute user_id=%s employee_id=%s date=%s total_points=%s",
            user_id,
            emp.employee_id,
            target_date,
            data["total_points"],
        )
        return success_response(
            data=data,
            message="Route loaded" if data["total_points"] else "No route points for date",
        )


# ──────────────────────────────────────────────
# ADMIN: EMPLOYEE SUMMARY
# GET /api/tracking/admin/employee/<id>/summary/
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee tracking summary",
    description="Returns real-time tracking summary for a single employee: online status, GPS health, today's distance, last location.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeSummaryNotFound")},
)
class AdminEmployeeSummaryAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        expire_old_workdays()
        now = timezone.now()
        today = now.date()

        emp = get_object_or_404(
            EmployeeProfile.objects.select_related(
                "user", "village", "village__district"
            ),
            user_id=user_id,
        )
        user = emp.user

        workday = (
            WorkDay.objects.filter(user=user, is_active=True)
            .order_by("-start_time")
            .first()
        )
        status_workday = workday
        if not status_workday:
            status_workday = (
                WorkDay.objects.filter(user=user).order_by("-start_time").first()
            )

        last_location = (
            LocationLog.objects.filter(user=user)
            .order_by("-recorded_at")
            .values("latitude", "longitude", "accuracy", "recorded_at")
            .first()
        )

        gps_off = False
        if workday:
            gps_off = AvailabilityEvent.objects.filter(
                user=user,
                workday=workday,
                event_type="GPS_OFF",
                end_time__isnull=True,
            ).exists()

        try:
            row = build_admin_tracking_row(
                emp=emp,
                user=user,
                workday=workday or status_workday,
                last_location=last_location,
                gps_off=gps_off,
                now=now,
                request=request,
            )
        except Exception:
            logger.exception("Employee summary tracking failed user_id=%s", user_id)
            row = {
                "user_id": user.id,
                "employee_id": emp.employee_id,
                "employee_name": user.username or emp.employee_id,
                "work_status": "NOT_WORKING",
                "connection": "OFFLINE",
                "gps_status": "GPS_OFF",
                "movement_status": "stopped",
                "active_workday": False,
            }

        today_distance_km = 0.0
        try:
            today_distance_km = _compute_distance_km(user.id, today)
        except Exception:
            logger.debug("Distance calc skipped user_id=%s", user_id, exc_info=True)

        row["today_distance_km"] = today_distance_km
        row["accuracy"] = last_location["accuracy"] if last_location else None
        row["is_on_field"] = row.get("active_workday", False)
        return Response(row)


# ──────────────────────────────────────────────
# ADMIN: EMPLOYEE ACTIVITY
# GET /api/tracking/admin/employee/<id>/activity/?date=YYYY-MM-DD
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee activity timeline",
    description="Returns combined activity timeline (workday events, location pings, GPS events) for an employee on a given date.",
    parameters=[
        OpenApiParameter("date", OpenApiTypes.DATE, description="Date (YYYY-MM-DD)")
    ],
    responses={200: SIMPLE_SUCCESS},
)
class AdminEmployeeActivityAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        emp = get_object_or_404(
            EmployeeProfile.objects.select_related("user"),
            user_id=user_id,
        )
        user = emp.user

        date_str = request.GET.get("date")
        target_date = parse_date(date_str) if date_str else timezone.now().date()

        workdays = WorkDay.objects.filter(user=user, date=target_date).order_by(
            "-start_time"
        )

        activity = []
        for wd in workdays:
            activity.append(
                {
                    "type": "workday_start",
                    "timestamp": wd.start_time.isoformat(),
                    "details": "Started work",
                }
            )
            if wd.end_time:
                activity.append(
                    {
                        "type": "workday_end",
                        "timestamp": wd.end_time.isoformat(),
                        "details": "Ended work",
                    }
                )

        locations = (
            LocationLog.objects.filter(
                user=user,
                recorded_at__date=target_date,
            )
            .order_by("-recorded_at")
            .values(
                "latitude", "longitude", "accuracy", "is_suspicious", "recorded_at"
            )[:50]
        )
        for loc in locations:
            activity.append(
                {
                    "type": "location",
                    "timestamp": loc["recorded_at"].isoformat(),
                    "latitude": float(loc["latitude"]),
                    "longitude": float(loc["longitude"]),
                    "accuracy": loc["accuracy"],
                    "is_suspicious": loc["is_suspicious"],
                }
            )

        events = AvailabilityEvent.objects.filter(
            user=user,
            start_time__date=target_date,
        ).order_by("-start_time")[:30]
        for ev in events:
            activity.append(
                {
                    "type": "availability",
                    "timestamp": ev.start_time.isoformat(),
                    "event_type": ev.event_type,
                    "details": f"{ev.event_type} started",
                }
            )
            if ev.end_time:
                activity.append(
                    {
                        "type": "availability",
                        "timestamp": ev.end_time.isoformat(),
                        "event_type": ev.event_type,
                        "details": f"{ev.event_type} ended",
                    }
                )

        activity.sort(key=lambda x: x["timestamp"], reverse=True)

        return Response(
            {
                "user_id": user_id,
                "date": str(target_date),
                "total_events": len(activity),
                "activity": activity,
            }
        )


# ──────────────────────────────────────────────
# Employee Stats (for Employees dashboard page)
# ──────────────────────────────────────────────
@extend_schema(
    tags=["Tracking"],
    summary="Employee stats summary",
    description="Returns total, online, and offline employee counts for today.",
    responses={200: SIMPLE_SUCCESS},
)
class EmployeeStatsAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        expire_old_workdays()
        total = EmployeeProfile.objects.count()
        today = timezone.localdate()
        now = timezone.now()
        online = sum(
            1
            for wd in WorkDay.objects.filter(date=today, is_active=True).only(
                "start_time", "last_heartbeat", "is_active"
            )
            if is_workday_within_duration(wd, now)
            and wd.last_heartbeat
            and wd.last_heartbeat >= now - timedelta(minutes=HEARTBEAT_STALE_MINUTES)
        )
        offline = total - online

        return Response(
            {
                "total": total,
                "online": online,
                "offline": offline,
            }
        )
