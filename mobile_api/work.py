"""Rewrite mobile work start/stop/status as DutySession compatibility wrappers."""

from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from tracking.legacy_work_compat import (
    legacy_end_via_duty,
    legacy_start_via_duty,
    log_deprecated_endpoint,
    mobile_work_status_payload,
)


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday start (compat → DutySession)",
    description=(
        "DEPRECATED. Use POST /api/v1/tracking/duty/start/. "
        "Compatibility wrapper → duty_service.start_duty."
    ),
    deprecated=True,
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
        }
    },
    responses={200: SIMPLE_SUCCESS, 400: error_schema("MobileWorkStartError")},
)
class MobileWorkStartAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        return legacy_start_via_duty(
            request,
            endpoint="/api/v1/mobile/work/start/",
            response_style="mobile",
        )


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday stop (compat → DutySession)",
    description=(
        "DEPRECATED. Use POST /api/v1/tracking/duty/end/. "
        "Compatibility wrapper → duty_service.end_duty."
    ),
    deprecated=True,
    request=None,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("MobileWorkStopError")},
)
class MobileWorkStopAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        return legacy_end_via_duty(
            request,
            endpoint="/api/v1/mobile/work/stop/",
            response_style="mobile",
        )


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday status (compat → DutySession)",
    description=(
        "DEPRECATED. Use GET /api/v1/tracking/duty/current/. "
        "Compatibility wrapper → serialize_duty_status."
    ),
    deprecated=True,
    responses={200: SIMPLE_SUCCESS},
)
class MobileWorkStatusAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        log_deprecated_endpoint(request=request, endpoint="/api/v1/mobile/work/status/")
        return success_response(data=mobile_work_status_payload(request.user))
