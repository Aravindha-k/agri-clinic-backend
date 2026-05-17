from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from visits.models import Visit
from visits.submitted import submitted_visits_qs
from tracking.models import WorkDay
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Dashboard"],
    summary="Mobile dashboard summary",
    description=(
        "Employee home KPIs: today's visits, all-time submitted visits, "
        "and active workday status. No draft/pending visit state."
    ),
    responses={200: SIMPLE_SUCCESS, 500: error_schema("MobileDashboardError")},
)
class MobileDashboardAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        try:
            user = request.user
            today = timezone.localdate()
            visit_qs = submitted_visits_qs().filter(employee=user)
            today_visits = visit_qs.filter(visit_date=today).count()
            total_visits = visit_qs.count()
            workday = WorkDay.objects.filter(user=user, is_active=True).first()
            data = {
                "today_visits": today_visits,
                "total_visits": total_visits,
                "completed_visits": total_visits,
                "pending_visits": 0,
                "active_visit": None,
                "work_status": "started" if workday else "not_started",
                "workday_id": workday.id if workday else None,
            }
            return success_response(data=data, message="Dashboard data fetched")
        except Exception as e:
            return error_response(message=str(e), status_code=500)
