from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from visits.models import Visit
from tracking.models import WorkDay
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Dashboard"],
    summary="Mobile dashboard summary",
    description="Returns today's counts, completed/pending totals, active visit, and workday status for mobile employees.",
    responses={200: SIMPLE_SUCCESS, 500: error_schema("MobileDashboardError")},
)
class MobileDashboardAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        try:
            user = request.user
            today = timezone.now().date()
            today_visits = Visit.objects.filter(employee=user, visit_date=today).count()
            completed_visits = Visit.objects.filter(
                employee=user, status="completed"
            ).count()
            pending_visits = Visit.objects.filter(
                employee=user, status="scheduled"
            ).count()
            active_visit = Visit.objects.filter(employee=user, status="active").first()
            from visits.serializers import VisitSerializer

            active_visit_data = (
                VisitSerializer(active_visit).data if active_visit else None
            )
            data = {
                "today_visits": today_visits,
                "completed_visits": completed_visits,
                "pending_visits": pending_visits,
                "active_visit": active_visit_data,
            }
            return success_response(data=data, message="Dashboard data fetched")
        except Exception as e:
            from utils.response import error_response

            return error_response(message=str(e), status_code=500)
