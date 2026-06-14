from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from tracking.workday_utils import expire_overlong_workdays_for_user
from .dashboard_metrics import mobile_dashboard_metrics


@extend_schema(
    tags=["Mobile", "Dashboard"],
    summary="Mobile dashboard summary",
    description=(
        "Employee home KPIs: visits today, farmers covered today, route distance/points, "
        "workday status. Follow-up scheduling is not part of the active workflow."
    ),
    responses={200: SIMPLE_SUCCESS, 500: error_schema("MobileDashboardError")},
)
class MobileDashboardAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        try:
            expire_overlong_workdays_for_user(request.user)
            data = mobile_dashboard_metrics(request.user)
            return success_response(data=data, message="Dashboard data fetched")
        except Exception as e:
            return error_response(message=str(e), status_code=500)
