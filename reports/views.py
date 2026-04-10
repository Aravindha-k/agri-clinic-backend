from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS

from .services import (
    employee_wise_visits,
    village_wise_visits,
    crop_problem_report,
)

_DATE_PARAMS = [
    OpenApiParameter(
        "start_date", OpenApiTypes.DATE, description="Start date (YYYY-MM-DD)"
    ),
    OpenApiParameter(
        "end_date", OpenApiTypes.DATE, description="End date (YYYY-MM-DD)"
    ),
]


@extend_schema(
    tags=["Reports"],
    summary="Employee-wise visit report",
    description="Returns visit counts and stats grouped by employee for the given date range.",
    parameters=_DATE_PARAMS,
    responses={200: SIMPLE_SUCCESS},
)
class EmployeeVisitReportAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        start = request.GET.get("start_date")
        end = request.GET.get("end_date")
        data = employee_wise_visits(start, end)
        return success_response(data=data)


@extend_schema(
    tags=["Reports"],
    summary="Village-wise visit report",
    description="Returns visit counts grouped by village for the given date range.",
    parameters=_DATE_PARAMS,
    responses={200: SIMPLE_SUCCESS},
)
class VillageVisitReportAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        start = request.GET.get("start_date")
        end = request.GET.get("end_date")
        data = village_wise_visits(start, end)
        return success_response(data=data)


@extend_schema(
    tags=["Reports"],
    summary="Crop problem report",
    description="Returns aggregated crop issues grouped by crop and problem type for the given date range.",
    parameters=_DATE_PARAMS,
    responses={200: SIMPLE_SUCCESS},
)
class CropProblemReportAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        start = request.GET.get("start_date")
        end = request.GET.get("end_date")
        data = crop_problem_report(start, end)
        return success_response(data=data)
