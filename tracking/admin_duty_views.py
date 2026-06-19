"""Admin duty tracking APIs (live map, routes)."""

from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from accounts.device_sessions import batch_device_status_map
from accounts.models import EmployeeProfile
from tracking.daily_summary import build_visit_stops
from tracking.duty_service import get_route_points_for_date, serialize_route_point_model
from tracking.employee_status import batch_gps_off_user_ids, build_status_for_live_employee
from tracking.models import DutySession, EmployeeGpsState, EmployeeLiveLocation
from tracking.route_utils import build_route_polyline, compute_route_distance_km
from tracking.workday_utils import expire_old_workdays
from utils.photo_urls import build_profile_photo_url
from utils.response import error_response, not_found_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


def _resolve_target_date(request):
    date_str = request.GET.get("date")
    if date_str:
        target = parse_date(date_str)
        if not target:
            return None, error_response(
                message="Invalid date. Use YYYY-MM-DD.",
                code="INVALID_DATE",
                status_code=400,
            )
        return target, None
    return timezone.localdate(), None


def _build_route_payload(*, emp, user_id: int, target_date, request) -> dict:
    points = get_route_points_for_date(user_id, target_date)
    route = [serialize_route_point_model(p) for p in points]
    polyline = build_route_polyline(route)
    distance_km = compute_route_distance_km(route)

    duty = (
        DutySession.objects.filter(user_id=user_id, date=target_date)
        .order_by("-start_time")
        .first()
    )
    stops = build_visit_stops(user_id, target_date)

    return {
        "date": str(target_date),
        "user_id": user_id,
        "employee_id": emp.employee_id,
        "duty_session_id": duty.id if duty else None,
        "total_points": len(route),
        "distance_km": distance_km,
        "polyline": polyline,
        "route": route,
        "stops": stops,
        "duty_started_at": duty.start_time.isoformat() if duty and duty.start_time else None,
        "duty_ended_at": duty.end_time.isoformat() if duty and duty.end_time else None,
    }


@extend_schema(
    tags=["Tracking"],
    summary="Admin: live employee map",
    responses={200: SIMPLE_SUCCESS},
)
class AdminTrackingLiveAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        expire_old_workdays()
        now = timezone.now()

        active_duty_user_ids = set(
            DutySession.objects.filter(is_active=True).values_list("user_id", flat=True)
        )

        employees = EmployeeProfile.objects.filter(
            is_active_employee=True
        ).select_related("user", "village", "village__district")

        employee_user_ids = [e.user_id for e in employees]
        live_rows = {
            row.user_id: row
            for row in EmployeeLiveLocation.objects.select_related("duty_session").filter(
                user_id__in=employee_user_ids
            )
        }
        gps_state_rows = {
            row.user_id: row
            for row in EmployeeGpsState.objects.filter(user_id__in=employee_user_ids)
        }
        device_status_map = batch_device_status_map(employee_user_ids)
        gps_off_user_ids = batch_gps_off_user_ids(
            list(active_duty_user_ids | set(live_rows.keys()))
        )

        features = []
        for emp in employees:
            live = live_rows.get(emp.user_id)
            on_duty = emp.user_id in active_duty_user_ids
            if not live and not on_duty:
                continue
            gps_state_row = gps_state_rows.get(emp.user_id)
            stored_gps_enabled = gps_state_row.gps_enabled if gps_state_row else None
            legacy_gps_off = (
                emp.user_id in gps_off_user_ids and stored_gps_enabled is None
            )
            status_fields = build_status_for_live_employee(
                user_id=emp.user_id,
                live_row=live,
                gps_state_row=gps_state_row,
                has_active_duty=on_duty,
                device_status=device_status_map.get(emp.user_id),
                gps_off=legacy_gps_off,
                last_heartbeat_at=(
                    live.duty_session.last_heartbeat
                    if live and live.duty_session_id and live.duty_session
                    else None
                ),
                now=now,
            )
            features.append(
                {
                    "user_id": emp.user_id,
                    "employee_id": emp.employee_id,
                    "username": emp.user.username,
                    "phone": emp.phone or "",
                    "profile_photo_url": build_profile_photo_url(request, emp.profile_photo),
                    "district": (
                        emp.village.district.name
                        if emp.village and emp.village.district
                        else None
                    ),
                    "is_on_duty": status_fields["is_on_duty"],
                    "duty_status": status_fields["duty_status"],
                    "gps_status": status_fields["gps_status"],
                    "gps_enabled": status_fields["gps_enabled"],
                    "location_permission_status": status_fields["location_permission_status"],
                    "background_tracking_enabled": status_fields["background_tracking_enabled"],
                    "gps_signal": status_fields["gps_signal"],
                    "legacy_gps_status": status_fields["legacy_gps_status"],
                    "connection": status_fields["connection"],
                    "tracking_health": status_fields["tracking_health"],
                    "duty_session_id": live.duty_session_id if live else None,
                    "latitude": float(live.latitude) if live else None,
                    "longitude": float(live.longitude) if live else None,
                    "accuracy": live.accuracy if live else None,
                    "speed": live.speed if live else None,
                    "battery_level": live.battery_level if live else None,
                    "last_gps_update": status_fields["last_gps_update"],
                    "last_seen_minutes": status_fields["last_seen_minutes"],
                    "last_update": status_fields["last_update"],
                    "last_update_age_minutes": status_fields["last_update_age_minutes"],
                }
            )

        return success_response(
            data={
                "updated_at": now.isoformat(),
                "count": len(features),
                "employees": features,
            },
            message="Live tracking loaded",
        )


@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee today route",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeTodayRouteAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        expire_old_workdays()
        try:
            emp = EmployeeProfile.objects.get(user_id=user_id, is_active_employee=True)
        except EmployeeProfile.DoesNotExist:
            return not_found_response("Employee not found")

        target_date = timezone.localdate()
        data = _build_route_payload(
            emp=emp, user_id=user_id, target_date=target_date, request=request
        )
        return success_response(data=data, message="Today route loaded")


@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee route by date",
    parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="YYYY-MM-DD")],
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeRouteByDateAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        expire_old_workdays()
        try:
            emp = EmployeeProfile.objects.get(user_id=user_id, is_active_employee=True)
        except EmployeeProfile.DoesNotExist:
            return not_found_response("Employee not found")

        target_date, err = _resolve_target_date(request)
        if err:
            return err

        data = _build_route_payload(
            emp=emp, user_id=user_id, target_date=target_date, request=request
        )
        return success_response(
            data=data,
            message="Route loaded" if data["total_points"] else "No route points for date",
        )
