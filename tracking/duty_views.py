"""Employee duty tracking APIs (start/end/location update)."""

from __future__ import annotations

import logging

from rest_framework import status
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.models import EmployeeProfile
from mobile_api.device_session import DeviceSessionRequiredMixin
from tracking.duty_service import (
    DutyTrackingError,
    bulk_update_locations,
    end_duty,
    serialize_duty_status,
    start_duty,
    update_location,
)
from utils.response import error_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema

logger = logging.getLogger(__name__)


def _duty_error(exc: DutyTrackingError):
    status = 403 if exc.code == "FORBIDDEN" else 400
    return error_response(message=exc.message, code=exc.code, status_code=status)


@extend_schema(
    tags=["Tracking"],
    summary="Start employee duty",
    responses={200: SIMPLE_SUCCESS, 201: SIMPLE_SUCCESS, 400: error_schema("DutyStartError")},
)
class DutyStartAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lat = request.data.get("latitude")
            lng = request.data.get("longitude")
            latitude = float(lat) if lat not in (None, "") else None
            longitude = float(lng) if lng not in (None, "") else None
            result = start_duty(
                request.user,
                latitude=latitude,
                longitude=longitude,
            )
        except DutyTrackingError as exc:
            return _duty_error(exc)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid latitude or longitude.",
                code="INVALID_COORDS",
                status_code=400,
            )
        payload = serialize_duty_status(request.user, result.duty)
        return success_response(
            data=payload,
            message="Duty started" if result.created else "Duty already active",
            status_code=201 if result.created else 200,
        )


@extend_schema(
    tags=["Tracking"],
    summary="Current employee duty",
    responses={200: SIMPLE_SUCCESS, 400: error_schema("DutyCurrentError")},
)
class DutyCurrentAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            data = serialize_duty_status(request.user)
        except DutyTrackingError as exc:
            return _duty_error(exc)
        return success_response(data=data, message="Current duty")


@extend_schema(
    tags=["Tracking"],
    summary="Duty day map by session id",
    description=(
        "Canonical workday map: duty timer, start/end markers, visit markers, "
        "route points, bounds, and summary. DutySession-scoped."
    ),
    responses={
        200: SIMPLE_SUCCESS,
        404: error_schema("DutyMapNotFound"),
        409: error_schema("SessionReplaced"),
    },
)
class DutyDayMapAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, duty_session_id):
        from tracking.day_map_service import DayMapError, build_duty_day_map, get_duty_for_map
        from visits.access import is_privileged_user

        # Staff/admin may omit device session (mixin exemption already applies).
        try:
            duty = get_duty_for_map(int(duty_session_id), viewer=request.user)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid duty session id.",
                code="VALIDATION_ERROR",
                status_code=400,
            )
        except DayMapError as exc:
            return error_response(
                message=exc.message,
                code=exc.code,
                status_code=exc.status,
            )

        include_live = duty.is_active and (
            duty.user_id == request.user.pk or is_privileged_user(request.user)
        )
        data = build_duty_day_map(
            duty,
            viewer=request.user,
            include_live_location=include_live,
        )
        return success_response(data=data, message="Duty day map")


@extend_schema(
    tags=["Tracking"],
    summary="Current duty day map",
    description="Convenience wrapper: map for the caller's current/latest duty.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("DutyMapNotFound")},
)
class DutyCurrentMapAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from tracking.day_map_service import DayMapError, build_duty_day_map
        from tracking.models import DutySession

        try:
            status_payload = serialize_duty_status(request.user)
        except DutyTrackingError as exc:
            return _duty_error(exc)

        duty_id = status_payload.get("duty_session_id")
        if not duty_id:
            return error_response(
                message="No duty session for map.",
                code="NOT_FOUND",
                status_code=404,
            )
        duty = (
            DutySession.objects.select_related("user", "workday")
            .filter(pk=duty_id, user=request.user)
            .first()
        )
        if duty is None:
            return error_response(
                message="Duty session not found.",
                code="NOT_FOUND",
                status_code=404,
            )
        data = build_duty_day_map(
            duty,
            viewer=request.user,
            include_live_location=duty.is_active,
        )
        return success_response(data=data, message="Current duty day map")


@extend_schema(
    tags=["Tracking"],
    summary="End employee duty",
    responses={200: SIMPLE_SUCCESS, 400: error_schema("DutyEndError")},
)
class DutyEndAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lat = request.data.get("latitude")
            lng = request.data.get("longitude")
            latitude = float(lat) if lat not in (None, "") else None
            longitude = float(lng) if lng not in (None, "") else None
            duty = end_duty(
                request.user,
                expected_duty_session_id=(
                    request.data.get("duty_session_id")
                    or request.data.get("expected_duty_session_id")
                ),
                latitude=latitude,
                longitude=longitude,
            )
        except DutyTrackingError as exc:
            return _duty_error(exc)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid latitude or longitude.",
                code="INVALID_COORDS",
                status_code=400,
            )
        payload = serialize_duty_status(request.user, duty)
        return success_response(
            data=payload,
            message="Duty ended",
        )


@extend_schema(
    tags=["Tracking"],
    summary="Update employee live location",
    description=(
        "Updates latest live location (single row per employee). "
        "Route points are saved only after ~35m movement or ~90s interval."
    ),
    responses={200: SIMPLE_SUCCESS, 400: error_schema("LocationUpdateError")},
)
class LocationUpdateAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = EmployeeProfile.objects.filter(user=request.user).first()
        if profile and not profile.is_active_employee:
            return error_response(
                message="Inactive employee",
                code="FORBIDDEN",
                status_code=403,
            )
        if "latitude" not in request.data or "longitude" not in request.data:
            return error_response(
                message="latitude and longitude are required.",
                code="VALIDATION_ERROR",
                status_code=400,
            )
        try:
            result = update_location(request.user, dict(request.data))
        except DutyTrackingError as exc:
            return _duty_error(exc)
        except ValueError as exc:
            return error_response(message=str(exc), code="INVALID_COORDS", status_code=400)

        return success_response(
            data=result,
            message="Location updated",
        )


def _extract_bulk_points(request) -> tuple[list | None, dict | None, str | None]:
    """Return (points, request_meta, error_message)."""
    if isinstance(request.data, list):
        return request.data, {}, None

    if not isinstance(request.data, dict):
        return None, None, "Expected list or object payload"

    points = (
        request.data.get("locations")
        or request.data.get("points")
        or []
    )
    if not isinstance(points, list):
        return None, None, "locations must be a list"

    meta = {
        "device_model": request.data.get("device_model"),
        "app_version": request.data.get("app_version"),
        "gps_enabled": request.data.get("gps_enabled"),
        "location_permission_status": request.data.get("location_permission_status"),
        "background_tracking_enabled": request.data.get("background_tracking_enabled"),
    }
    return points, meta, None


@extend_schema(
    tags=["Tracking"],
    summary="Bulk sync offline GPS points",
    description=(
        "Batch-upload queued GPS fixes from offline storage. "
        "Updates EmployeeLiveLocation and saves EmployeeRoutePoint using "
        "the same ~35m / ~90s throttle as single location updates."
    ),
    responses={201: SIMPLE_SUCCESS, 207: SIMPLE_SUCCESS, 400: error_schema("BulkSyncError")},
)
class BulkLocationSyncAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = EmployeeProfile.objects.filter(user=request.user).first()
        if profile and not profile.is_active_employee:
            return error_response(
                message="Inactive employee",
                code="FORBIDDEN",
                status_code=403,
            )

        points, meta, parse_error = _extract_bulk_points(request)
        if parse_error:
            return error_response(
                message=parse_error,
                code="INVALID_PAYLOAD",
                status_code=400,
            )

        if not points:
            return error_response(
                message="At least one location point is required.",
                code="EMPTY_BATCH",
                status_code=400,
            )

        try:
            result = bulk_update_locations(
                request.user,
                points,
                device_model=(meta or {}).get("device_model"),
                app_version=(meta or {}).get("app_version"),
                request_meta=meta,
            )
        except DutyTrackingError as exc:
            return _duty_error(exc)

        status_code = (
            status.HTTP_201_CREATED
            if result["failed_count"] == 0
            else status.HTTP_207_MULTI_STATUS
        )
        message = (
            "Bulk locations synced"
            if result["failed_count"] == 0
            else "Bulk locations synced with partial failures"
        )
        return success_response(data=result, message=message, status_code=status_code)
