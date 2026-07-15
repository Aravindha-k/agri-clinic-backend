from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from tracking.legacy_work_compat import (
    legacy_end_via_duty,
    legacy_start_via_duty,
    log_deprecated_endpoint,
    worklog_status_payload,
)
from tracking.models import DutySession
from mobile_api.device_session import DeviceSessionRequiredMixin
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


@extend_schema(
    tags=["Tracking"],
    summary="Start work session (WorkLog compat → DutySession)",
    description="Deprecated. Proxies to DutySession; does not create an independent WorkLog clock.",
    request=None,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("WorkLogAlreadyActive")},
)
class WorkLogStartAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return legacy_start_via_duty(
            request,
            endpoint="/api/v1/tracking/work/start/",
            response_style="worklog",
        )


@extend_schema(
    tags=["Tracking"],
    summary="End work session (WorkLog compat → DutySession)",
    description="Deprecated. Proxies to DutySession.",
    request=None,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("WorkLogNotFound")},
)
class WorkLogEndAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return legacy_end_via_duty(
            request,
            endpoint="/api/v1/tracking/work/end/",
            response_style="worklog",
        )


@extend_schema(
    tags=["Tracking"],
    summary="Current work session status (WorkLog compat → DutySession)",
    description="Deprecated. Returns active DutySession mapped to WorkLog fields.",
    responses={200: SIMPLE_SUCCESS},
)
class WorkLogStatusAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        log_deprecated_endpoint(
            request=request, endpoint="/api/v1/tracking/work/status/"
        )
        return success_response(data=worklog_status_payload(request.user))


@extend_schema(
    tags=["Tracking"],
    summary="Work session history (DutySession)",
    description="Deprecated WorkLog history path; returns DutySession history for the employee.",
    responses={200: SIMPLE_SUCCESS},
)
class WorkLogHistoryAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        log_deprecated_endpoint(
            request=request, endpoint="/api/v1/tracking/work/history/"
        )
        rows = (
            DutySession.objects.filter(user=request.user)
            .order_by("-start_time")[:90]
        )
        data = []
        for duty in rows:
            duration = None
            if duty.start_time and duty.end_time:
                duration = str(duty.end_time - duty.start_time)
            data.append(
                {
                    "id": duty.id,
                    "employee": duty.user_id,
                    "start_time": duty.start_time,
                    "end_time": duty.end_time,
                    "total_duration": duration,
                    "is_active": duty.is_active,
                    "duty_session_id": duty.id,
                    "workday_id": duty.workday_id,
                }
            )
        return success_response(data=data)
