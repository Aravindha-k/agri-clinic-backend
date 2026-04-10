from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS
from visits.models import Visit
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Reports"],
    summary="Mobile quick reports",
    description="Returns daily and monthly visit counts for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS},
)
class MobileReportsAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        daily_count = Visit.objects.filter(employee=user, visit_date=today).count()
        month_start = today.replace(day=1)
        monthly_count = Visit.objects.filter(
            employee=user, visit_date__gte=month_start
        ).count()
        data = {
            "daily": daily_count,
            "monthly": monthly_count,
        }
        return success_response(data=data, message="Reports fetched")
