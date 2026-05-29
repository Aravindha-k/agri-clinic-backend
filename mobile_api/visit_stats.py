from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS
from visits.submitted import submitted_visits_qs
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Mobile visit stats",
    description=(
        "Returns today's submitted visit counts for the logged-in employee."
    ),
    responses={200: SIMPLE_SUCCESS},
)
class MobileVisitStatsAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        qs = submitted_visits_qs().filter(employee=user)
        today_count = qs.filter(visit_date=today).count()
        total_count = qs.count()
        data = {
            "today_visits": today_count,
            "total_visits": total_count,
            "completed": total_count,
            "pending": 0,
        }
        return success_response(data=data, message="Visit stats fetched")
