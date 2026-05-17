from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS
from visits.submitted import submitted_visits_qs
from visits.visit_response import crop_display_name

from .permissions import IsEmployeeUser


@extend_schema(
    tags=["Mobile", "Map"],
    summary="Mobile visit map markers",
    description=(
        "GPS markers from the employee's submitted visits (not farmer master pins). "
        "Use for field map on the mobile tracking/visits screens."
    ),
    responses={200: SIMPLE_SUCCESS},
)
class MobileVisitMapAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        visits = (
            submitted_visits_qs()
            .filter(employee=request.user)
            .select_related("farmer", "crop", "village")
            .order_by("-visit_date", "-id")[:500]
        )
        markers = []
        for visit in visits:
            markers.append(
                {
                    "visit_id": visit.id,
                    "farmer_id": visit.farmer_id,
                    "farmer_name": visit.farmer_name or (
                        visit.farmer.name if visit.farmer_id else None
                    ),
                    "latitude": visit.latitude,
                    "longitude": visit.longitude,
                    "visit_date": str(visit.visit_date) if visit.visit_date else None,
                    "crop": crop_display_name(visit),
                    "village": visit.village.name if visit.village_id else None,
                }
            )
        return success_response(data={"markers": markers}, message="Map markers fetched")
