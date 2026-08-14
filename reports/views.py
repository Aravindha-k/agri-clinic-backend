from rest_framework.views import APIView
from utils.permissions import IsStaffAdmin

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS

from .services import (
    employee_wise_visits,
    village_wise_visits,
    crop_problem_report,
)
from .summary import build_admin_report_summary
from visits.date_filters import parse_report_date_params

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
    permission_classes = [IsStaffAdmin]

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
    permission_classes = [IsStaffAdmin]

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
    permission_classes = [IsStaffAdmin]

    def get(self, request):
        start = request.GET.get("start_date")
        end = request.GET.get("end_date")
        data = crop_problem_report(start, end)
        return success_response(data=data)


@extend_schema(
    tags=["Reports"],
    summary="Admin report summary aggregates",
    description=(
        "Server-side visit aggregates for the Admin Reports page. "
        "Supports from/to (or start_date/end_date), employee, and district filters. "
        "Does not return raw visit rows."
    ),
    parameters=[
        OpenApiParameter("from", OpenApiTypes.DATE, description="Start date YYYY-MM-DD"),
        OpenApiParameter("to", OpenApiTypes.DATE, description="End date YYYY-MM-DD"),
        *_DATE_PARAMS,
        OpenApiParameter("employee", OpenApiTypes.STR, description="User id or employee_id"),
        OpenApiParameter("district", OpenApiTypes.STR, description="District id or name"),
    ],
    responses={200: SIMPLE_SUCCESS},
)
class AdminReportSummaryAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def get(self, request):
        start, end = parse_report_date_params(request.query_params)
        data = build_admin_report_summary(
            start=start,
            end=end,
            employee=request.query_params.get("employee"),
            district=request.query_params.get("district"),
        )
        return success_response(data=data)
