"""Admin duty tracking APIs (live map, routes)."""

from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from utils.permissions import IsStaffAdmin
from rest_framework.views import APIView

from accounts.device_sessions import batch_device_status_map
from accounts.models import EmployeeProfile
from tracking.duty_timer import compute_duty_timer
from tracking.employee_status import batch_gps_off_user_ids, build_status_for_live_employee
from tracking.duty_service import DutyTrackingError, end_duty, serialize_duty_status
from tracking.models import DutySession, EmployeeGpsState, EmployeeLiveLocation
from tracking.workday_utils import expire_old_workdays
from utils.photo_urls import build_profile_photo_url
from utils.response import error_response, not_found_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema

# Prevent proxies/browsers from serving a stale Live Tracking payload.
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def _no_store_response(response):
    for key, value in _NO_STORE_HEADERS.items():
        response[key] = value
    return response


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
    """Compatibility adapter → canonical day_map_service."""
    from tracking.day_map_service import build_admin_route_compat_payload
    from tracking.legacy_work_compat import log_deprecated_endpoint

    log_deprecated_endpoint(
        request=request,
        endpoint=f"/api/admin/tracking/employee/{user_id}/route",
    )
    duty = (
        DutySession.objects.filter(user_id=user_id, date=target_date)
        .order_by("-start_time")
        .first()
    )
    return build_admin_route_compat_payload(
        duty=duty,
        emp=emp,
        user_id=user_id,
        target_date=target_date,
    )


@extend_schema(
    tags=["Tracking"],
    summary="Admin: live employee map",
    responses={200: SIMPLE_SUCCESS},
)
class AdminTrackingLiveAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def get(self, request):
        expire_old_workdays()
        now = timezone.now()

        from tracking.live_tracking_service import (
            TRACKING_ONLINE,
            resolve_duty_display_status,
            tracking_status_sort_key,
        )

        # Active duties only — ended employees leave the live list.
        active_duties = {
            d.user_id: d
            for d in DutySession.objects.filter(is_active=True).select_related(
                "workday", "user"
            )
        }
        active_duty_user_ids = list(active_duties.keys())
        if not active_duty_user_ids:
            return _no_store_response(
                success_response(
                    data={
                        "updated_at": now.isoformat(),
                        "server_now": now.isoformat(),
                        "count": 0,
                        "employees": [],
                        "online_count": 0,
                        "stale_count": 0,
                        "offline_count": 0,
                        "no_location_count": 0,
                    },
                    message="Live tracking loaded",
                )
            )

        employees = {
            e.user_id: e
            for e in EmployeeProfile.objects.filter(
                user_id__in=active_duty_user_ids,
                is_active_employee=True,
            ).select_related("user", "village", "village__district")
        }
        live_rows = {
            row.user_id: row
            for row in EmployeeLiveLocation.objects.filter(
                user_id__in=active_duty_user_ids
            )
        }
        gps_state_rows = {
            row.user_id: row
            for row in EmployeeGpsState.objects.filter(user_id__in=active_duty_user_ids)
        }
        device_status_map = batch_device_status_map(active_duty_user_ids)
        gps_off_user_ids = batch_gps_off_user_ids(active_duty_user_ids)

        features = []
        for user_id, duty in active_duties.items():
            emp = employees.get(user_id)
            if emp is None:
                continue
            live = live_rows.get(user_id)
            device_status = device_status_map.get(user_id) or {}
            gps_state_row = gps_state_rows.get(user_id)
            stored_gps_enabled = gps_state_row.gps_enabled if gps_state_row else None
            legacy_gps_off = user_id in gps_off_user_ids and stored_gps_enabled is None

            # Prefer live-state heartbeat; fall back to duty.last_heartbeat.
            last_heartbeat_at = None
            if live and live.last_heartbeat_at:
                last_heartbeat_at = live.last_heartbeat_at
            elif duty.last_heartbeat:
                last_heartbeat_at = duty.last_heartbeat

            status_fields = build_status_for_live_employee(
                user_id=user_id,
                live_row=live,
                gps_state_row=gps_state_row,
                has_active_duty=True,
                device_status=device_status,
                gps_off=legacy_gps_off,
                last_heartbeat_at=last_heartbeat_at,
                now=now,
            )
            timer = compute_duty_timer(duty, now=now)
            display_name = (
                f"{emp.user.first_name} {emp.user.last_name}".strip()
                or emp.user.username
            )
            lat = float(live.latitude) if live and live.latitude is not None else None
            lng = float(live.longitude) if live and live.longitude is not None else None
            features.append(
                {
                    "user_id": user_id,
                    "employee_id": emp.employee_id,
                    "employee_code": emp.employee_id,
                    "employee_name": display_name,
                    "username": emp.user.username,
                    "phone": emp.phone or "",
                    "profile_photo_url": build_profile_photo_url(
                        request, emp.profile_photo
                    ),
                    "district": (
                        emp.village.district.name
                        if emp.village and emp.village.district
                        else None
                    ),
                    "area_name": (
                        emp.village.name if emp.village else None
                    ),
                    "location_name": None,
                    "is_on_duty": True,
                    "active_workday": True,
                    "duty_status": status_fields["duty_status"],
                    "duty_display_status": resolve_duty_display_status(duty),
                    "tracking_status": status_fields["tracking_status"],
                    "gps_status": status_fields["gps_status"],
                    "gps_enabled": status_fields["gps_enabled"],
                    "permission_granted": status_fields["permission_granted"],
                    "tracking_service_active": status_fields[
                        "tracking_service_active"
                    ],
                    "location_permission_status": status_fields[
                        "location_permission_status"
                    ],
                    "background_tracking_enabled": status_fields[
                        "background_tracking_enabled"
                    ],
                    "gps_signal": status_fields["gps_signal"],
                    "legacy_gps_status": status_fields["legacy_gps_status"],
                    "connection": status_fields["connection"],
                    "tracking_health": status_fields["tracking_health"],
                    "duty_session_id": duty.pk,
                    "workday_id": duty.workday_id,
                    "started_at": timer.get("started_at"),
                    "expected_end_at": timer.get("expected_end_at"),
                    "latitude": lat,
                    "longitude": lng,
                    "latest_accuracy": live.accuracy if live else None,
                    "accuracy": live.accuracy if live else None,
                    "speed": live.speed if live else None,
                    "battery_level": live.battery_level if live else None,
                    "location_recorded_at": status_fields["location_recorded_at"],
                    "last_heartbeat_at": status_fields["last_heartbeat_at"],
                    "last_gps_update": status_fields["last_gps_update"],
                    "last_seen_minutes": status_fields["last_seen_minutes"],
                    "last_update": status_fields["last_update"],
                    "last_update_age_minutes": status_fields[
                        "last_update_age_minutes"
                    ],
                    "server_now": now.isoformat(),
                    "device_status": device_status,
                    "device_information": {
                        "device_name": device_status.get("device_name"),
                        "device_model": device_status.get("device_model"),
                        "platform": device_status.get("platform"),
                        "app_version": device_status.get("app_version"),
                        "active_device_id": device_status.get("active_device_id"),
                        "is_active": device_status.get("is_active"),
                    },
                    "last_login": device_status.get("last_login_at"),
                    "last_seen": device_status.get("last_seen_at"),
                }
            )

        features.sort(
            key=lambda row: (
                tracking_status_sort_key(row.get("tracking_status") or ""),
                (row.get("employee_name") or row.get("username") or "").lower(),
            )
        )

        return _no_store_response(
            success_response(
                data={
                    "updated_at": now.isoformat(),
                    "server_now": now.isoformat(),
                    "count": len(features),
                    "employees": features,
                    "online_count": sum(
                        1
                        for row in features
                        if row.get("tracking_status") == TRACKING_ONLINE
                    ),
                    "stale_count": sum(
                        1 for row in features if row.get("tracking_status") == "STALE"
                    ),
                    "offline_count": sum(
                        1
                        for row in features
                        if row.get("tracking_status") == "OFFLINE"
                    ),
                    "no_location_count": sum(
                        1
                        for row in features
                        if row.get("tracking_status") == "NO_LOCATION_YET"
                    ),
                },
                message="Live tracking loaded",
            )
        )


@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee today route",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeTodayRouteAPI(APIView):
    permission_classes = [IsStaffAdmin]

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
    permission_classes = [IsStaffAdmin]

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
        has_content = bool(
            data.get("marker_count")
            or data.get("total_points")
            or data.get("has_start_marker")
        )
        return success_response(
            data=data,
            message="Route loaded" if has_content else "No route points for date",
        )


@extend_schema(
    tags=["Tracking"],
    summary="Admin: force-end employee duty",
    description=(
        "Authorized admin action to complete an employee's active workday. "
        "Field employees cannot call the mobile duty/end endpoint."
    ),
    responses={200: SIMPLE_SUCCESS, 403: error_schema("Forbidden"), 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeEndDutyAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def post(self, request, user_id):
        try:
            emp = EmployeeProfile.objects.select_related("user").get(
                user_id=user_id, is_active_employee=True
            )
        except EmployeeProfile.DoesNotExist:
            return not_found_response("Employee not found")

        try:
            lat = request.data.get("latitude")
            lng = request.data.get("longitude")
            latitude = float(lat) if lat not in (None, "") else None
            longitude = float(lng) if lng not in (None, "") else None
            duty = end_duty(
                emp.user,
                expected_duty_session_id=(
                    request.data.get("duty_session_id")
                    or request.data.get("expected_duty_session_id")
                ),
                latitude=latitude,
                longitude=longitude,
            )
        except DutyTrackingError as exc:
            status_code = 403 if exc.code == "FORBIDDEN" else 400
            return error_response(message=exc.message, code=exc.code, status_code=status_code)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid latitude or longitude.",
                code="INVALID_COORDS",
                status_code=400,
            )

        payload = serialize_duty_status(emp.user, duty)
        return success_response(data=payload, message="Employee duty ended by admin")
