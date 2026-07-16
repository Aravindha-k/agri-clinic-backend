"""Mobile location push — compatibility wrapper → canonical GPS service."""

from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from tracking.gps_service import GpsTrackingError, update_gps_point


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile location push (compat → DutySession route points)",
    description=(
        "Deprecated LocationLog-only path. Now proxies to the canonical GPS "
        "service (EmployeeRoutePoint owned by active DutySession)."
    ),
    responses={200: SIMPLE_SUCCESS, 400: error_schema("MobileTrackingError")},
)
class MobileTrackingAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        try:
            result = update_gps_point(request.user, dict(request.data))
        except GpsTrackingError as exc:
            code = 403 if exc.code in {"FORBIDDEN", "ACCOUNT_DISABLED"} else 400
            return error_response(
                message=exc.message,
                code=exc.code,
                status_code=code,
            )
        return success_response(
            data={
                "location_id": result.get("location_log_id") or result.get("route_point_id"),
                "route_point_id": result.get("route_point_id"),
                "duty_session_id": result.get("duty_session_id"),
                "duplicate": result.get("duplicate", False),
                "client_point_id": result.get("client_point_id"),
            },
            message="Location saved",
        )
