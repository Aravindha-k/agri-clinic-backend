from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db.models import Count, Max, Q
from visits.models import Visit
from utils.schema import PAGINATION_PARAMS, SEARCH_PARAM, SIMPLE_SUCCESS


class FarmerSummaryPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


@extend_schema(
    tags=["Farmers", "Visits"],
    summary="Farmer summary from visits",
    description="Returns paginated farmer summaries aggregated from visit data.",
    parameters=PAGINATION_PARAMS + [SEARCH_PARAM],
    responses={200: SIMPLE_SUCCESS},
)
class FarmerSummaryAPI(APIView):
    @extend_schema(operation_id="v1_visits_farmer_list")
    def get(self, request):
        search = request.GET.get("search")
        qs = (
            Visit.objects.values(
                "farmer_phone",
                "farmer_name",
                "village__name",
            )
            .annotate(total_visits=Count("id"), last_visit_date=Max("visit_date"))
            .order_by("-last_visit_date")
        )
        if search:
            qs = qs.filter(
                Q(farmer_name__icontains=search) | Q(farmer_phone__icontains=search)
            )
        paginator = FarmerSummaryPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [
            {
                "farmer_name": row["farmer_name"],
                "farmer_phone": row["farmer_phone"],
                "village_name": row["village__name"],
                "total_visits": row["total_visits"],
                "last_visit_date": row["last_visit_date"],
            }
            for row in page
        ]
        return paginator.get_paginated_response(results)


@extend_schema(
    tags=["Farmers", "Visits"],
    summary="Farmer detail by phone",
    description="Returns consolidated farmer detail and visit history by phone number.",
    parameters=[OpenApiParameter("phone", OpenApiTypes.STR, OpenApiParameter.PATH)],
    responses={200: SIMPLE_SUCCESS},
)
class FarmerDetailAPI(APIView):
    @extend_schema(operation_id="v1_visits_farmer_detail")
    def get(self, request, phone):
        visits = Visit.objects.filter(farmer_phone=phone).order_by("-visit_date")
        if not visits.exists():
            return Response({"error": "Farmer not found"}, status=404)
        first = visits.first()
        data = {
            "farmer_name": first.farmer_name,
            "farmer_phone": first.farmer_phone,
            "village_name": first.village.name if first.village else None,
            "visits": [
                {
                    "id": v.id,
                    "visit_date": v.visit_date,
                    "crop_name": v.crop_name,
                    "notes": v.notes,
                    "status": v.status,
                }
                for v in visits
            ],
        }
        return Response(data)
