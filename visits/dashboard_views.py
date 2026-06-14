from django.db.models import Q
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS

from visits.models import Visit
from visits.kpi_status import COMPLETED_STATUSES
from masters.models import Farmer, CropIssue


@extend_schema(
    tags=["Dashboard"],
    summary="Employee dashboard counters",
    description="Returns today's visit counters and key totals for dashboard widgets.",
    responses={200: SIMPLE_SUCCESS},
)
class DashboardAPI(APIView):
    """
    GET /api/v1/dashboard/
    Returns counts scoped to the requesting employee.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.now().date()

        today_visits = Visit.objects.filter(employee=user, visit_date=today).count()
        completed_visits = Visit.objects.filter(
            employee=user, visit_date=today, status__in=COMPLETED_STATUSES
        ).count()

        if user.is_staff:
            farmers_count = Farmer.objects.count()
            issues_count = CropIssue.objects.filter(status="open").count()
        else:
            farmers_count = Farmer.objects.filter(assigned_employee=user).count()
            issues_count = CropIssue.objects.filter(
                visit__employee=user, status="open"
            ).count()

        return success_response(
            data={
                "today_visits": today_visits,
                "completed_visits": completed_visits,
                "farmers": farmers_count,
                "issues": issues_count,
            }
        )


@extend_schema(
    tags=["Dashboard", "Farmers"],
    summary="Map farmers",
    description="Returns farmer markers with id, name, lat, lng and crop info for map rendering.",
    responses={200: SIMPLE_SUCCESS},
)
class MapFarmersAPI(APIView):
    """
    GET /api/v1/map/farmers/
    Returns farmer markers with id, name, lat, lng, current crop.
    Only farmers with GPS data are returned.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from farmers.helpers import parse_gps_location

        qs = Farmer.objects.exclude(
            Q(gps_location="") | Q(gps_location__isnull=True)
        ).select_related("village")

        farmers = list(qs)
        farmer_ids = [f.id for f in farmers]

        crop_by_farmer_id: dict[int, str | None] = {}
        if farmer_ids:
            for visit in (
                Visit.objects.filter(farmer_id__in=farmer_ids, crop__isnull=False)
                .select_related("crop")
                .order_by("farmer_id", "-visit_date", "-id")
            ):
                if visit.farmer_id not in crop_by_farmer_id:
                    crop_by_farmer_id[visit.farmer_id] = (
                        visit.crop.name_en if visit.crop else None
                    )

        markers = []
        for farmer in farmers:
            lat, lng = parse_gps_location(farmer.gps_location)
            if lat is None or lng is None:
                continue

            markers.append(
                {
                    "id": farmer.id,
                    "name": farmer.name,
                    "latitude": lat,
                    "longitude": lng,
                    "crop": crop_by_farmer_id.get(farmer.id),
                }
            )

        return success_response(data=markers)
