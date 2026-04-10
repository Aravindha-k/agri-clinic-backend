from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from visits.models import Visit
from masters.models import Farmer
from tracking.models import LocationLog, WorkDay
from accounts.models import EmployeeProfile
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS

from . import services as dashboard_services

_DAYS_PARAM = OpenApiParameter(
    "days",
    OpenApiTypes.INT,
    description="Number of days to look back (1–365). Default: 30.",
)


@extend_schema(
    tags=["Dashboard"],
    summary="Dashboard summary stats (alias)",
    description="Backward-compatible alias for `/api/v1/dashboard/summary/`. Returns aggregated KPIs.",
    responses={200: SIMPLE_SUCCESS},
)
class DashboardView(APIView):
    """GET /api/v1/dashboard/  – backward-compatible alias."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = dashboard_services.get_stats()
        return success_response(data=data)


@extend_schema(
    tags=["Dashboard"],
    summary="Dashboard summary stats",
    description=(
        "Returns top-level KPIs: total visits, active employees, farmer coverage, "
        "today's visit count, etc."
    ),
    responses={200: SIMPLE_SUCCESS},
)
class DashboardSummaryAPI(APIView):
    """GET /api/v1/dashboard/summary/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = dashboard_services.get_stats()
        return success_response(data=data)


@extend_schema(
    tags=["Dashboard"],
    summary="Visit trends",
    description="Returns daily visit counts for the last N days, grouped by date.",
    parameters=[_DAYS_PARAM],
    responses={200: SIMPLE_SUCCESS},
)
class VisitTrendsAPI(APIView):
    """GET /api/v1/dashboard/visit-trends/?days=30"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = int(request.query_params.get("days", 30))
        days = max(1, min(days, 365))
        data = dashboard_services.get_visit_trends(days=days)
        return success_response(data=data)


@extend_schema(
    tags=["Dashboard"],
    summary="Employee performance leaderboard",
    description="Returns per-employee visit counts and stats for the last N days.",
    parameters=[_DAYS_PARAM],
    responses={200: SIMPLE_SUCCESS},
)
class EmployeePerformanceAPI(APIView):
    """GET /api/v1/dashboard/employee-performance/?days=30"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = int(request.query_params.get("days", 30))
        days = max(1, min(days, 365))
        data = dashboard_services.get_employee_performance(days=days)
        return success_response(data=data)


@extend_schema(
    tags=["Dashboard"],
    summary="Village visit heatmap",
    description="Returns the top-N most visited villages with visit counts, for heatmap visualization.",
    parameters=[
        OpenApiParameter(
            "top",
            OpenApiTypes.INT,
            description="Number of villages to return (1–100). Default: 20.",
        )
    ],
    responses={200: SIMPLE_SUCCESS},
)
class VillageHeatmapAPI(APIView):
    """GET /api/v1/dashboard/village-heatmap/?top=20"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        top_n = int(request.query_params.get("top", 20))
        top_n = max(1, min(top_n, 100))
        data = dashboard_services.get_village_heatmap(top_n=top_n)
        return success_response(data=data)
