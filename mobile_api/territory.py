"""Mobile employee territory API."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated

from accounts.territory import build_employee_territory_payload
from mobile_api.device_session import MobileEmployeeAPIView
from mobile_api.permissions import IsEmployeeUser
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


@extend_schema(
    tags=["Mobile", "Territory"],
    summary="Logged-in employee's assigned villages",
    description=(
        "Active villages operationally assigned to the authenticated field "
        "employee. Empty when no villages are assigned (fail-closed)."
    ),
    responses={200: SIMPLE_SUCCESS, 403: error_schema("Forbidden")},
)
class MobileTerritoryAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        payload = build_employee_territory_payload(request.user)
        return success_response(data=payload, message="Territory fetched")
