from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS
from visits.models import Visit
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Mobile visit stats",
    description="Returns today's visit counts for the logged-in employee: total, completed, pending.",
    responses={200: SIMPLE_SUCCESS},
)
class MobileVisitStatsAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        today_visits = Visit.objects.filter(employee=user, visit_date=today).count()
        completed = Visit.objects.filter(
            employee=user, visit_date=today, status="completed"
        ).count()
        pending = Visit.objects.filter(
            employee=user, visit_date=today, status="pending"
        ).count()
        data = {
            "today_visits": today_visits,
            "completed": completed,
            "pending": pending,
        }
        return success_response(data=data, message="Visit stats fetched")
