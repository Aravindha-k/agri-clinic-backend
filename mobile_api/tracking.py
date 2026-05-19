from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from tracking.models import LocationLog, WorkDay
from tracking.serializers import LocationLogCreateSerializer
from tracking.workday_utils import WORKDAY_EXPIRED_MESSAGE, expire_overlong_workdays_for_user
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Tracking"],
    summary="Mobile location push",
    description="Creates a location log for the authenticated employee's active workday.",
    request=LocationLogCreateSerializer,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("MobileTrackingError")},
)
class MobileTrackingAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def post(self, request):
        user = request.user
        expire_overlong_workdays_for_user(user)
        workday = WorkDay.objects.filter(user=user, is_active=True).first()
        if not workday:
            return error_response(
                message=WORKDAY_EXPIRED_MESSAGE,
                status_code=400,
            )
        serializer = LocationLogCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        location = serializer.save()
        return success_response(
            data={"location_id": location.id}, message="Location saved"
        )
