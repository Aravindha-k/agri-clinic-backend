from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from tracking.models import WorkDay
from tracking.workday_utils import (
    WORKDAY_EXPIRED_MESSAGE,
    clear_live_tracking_for_user,
    expire_overlong_workdays_for_user,
    is_workday_within_duration,
)
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday start",
    description="Starts an active workday for the logged-in employee.",
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
        logger.debug(f"MOBILE WORK START PAYLOAD: {request.data}")
        user = request.user
        today = timezone.localdate()
        expire_overlong_workdays_for_user(user)
        if WorkDay.objects.filter(user=user, is_active=True).exists():
            return error_response(message="Workday already started", status_code=400)
        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")
        now = timezone.now()
        workday_kwargs = {
            "user": user,
            "date": today,
            "start_time": now,
            "is_active": True,
            "last_heartbeat": now,
        }
        if latitude is not None:
            workday_kwargs["latitude"] = latitude
        if longitude is not None:
            workday_kwargs["longitude"] = longitude
        try:
            WorkDay.objects.create(**workday_kwargs)
        except Exception as e:
            return error_response(
                message="Validation error", errors={"detail": str(e)}, status_code=400
            )
        return success_response(message="Workday started")


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday stop",
    description="Stops the current active workday for the logged-in employee.",
    request=None,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("MobileWorkStopError")},
)
class MobileWorkStopAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        logger.debug(f"MOBILE WORK STOP PAYLOAD: {request.data}")
        user = request.user
        expire_overlong_workdays_for_user(user)
        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        if not workday:
            return error_response(message="No active workday", status_code=400)
        workday.end_time = timezone.now()
        workday.is_active = False
        workday.auto_ended = False
        workday.save(update_fields=["end_time", "is_active", "auto_ended"])
        clear_live_tracking_for_user(user.pk)
        return success_response(message="Workday stopped")


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday status",
    description="Returns whether workday is started, expired, or not_started.",
    responses={200: SIMPLE_SUCCESS},
)
class MobileWorkStatusAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        user = request.user
        expire_overlong_workdays_for_user(user)
        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        if workday and is_workday_within_duration(workday):
            status_str = "started"
        elif WorkDay.objects.filter(user=user, auto_ended=True).exists():
            status_str = "expired"
        else:
            status_str = "not_started"
        payload = {"work_status": status_str}
        if status_str == "expired":
            payload["message"] = WORKDAY_EXPIRED_MESSAGE
            payload["code"] = "workday_expired"
        elif workday:
            payload["workday_id"] = workday.id
        return success_response(data=payload)
