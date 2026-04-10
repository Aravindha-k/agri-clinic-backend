from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from tracking.models import WorkDay
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
class MobileWorkStartAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        logger.debug(f"MOBILE WORK START PAYLOAD: {request.data}")
        user = request.user
        today = timezone.localdate()
        # Accept empty or minimal payload
        if WorkDay.objects.filter(user=user, is_active=True).exists():
            return error_response(message="Workday already started", status_code=400)
        # Optionally accept latitude/longitude if provided, but not required
        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")
        workday_kwargs = {
            "user": user,
            "date": today,
            "start_time": timezone.now(),
            "is_active": True,
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
class MobileWorkStopAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        logger.debug(f"MOBILE WORK STOP PAYLOAD: {request.data}")
        user = request.user
        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        if not workday:
            return error_response(message="No active workday", status_code=400)
        workday.end_time = timezone.now()
        workday.is_active = False
        workday.save(update_fields=["end_time", "is_active"])
        return success_response(message="Workday stopped")


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile workday status",
    description="Returns whether workday is started or not_started for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS},
)
class MobileWorkStatusAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        user = request.user
        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        status_str = "started" if workday else "not_started"
        return success_response(data={"work_status": status_str})
