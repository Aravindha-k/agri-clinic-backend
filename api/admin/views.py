from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.mixins import (
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.viewsets import GenericViewSet
from drf_spectacular.utils import extend_schema

from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS

from masters.models import (
    Farmer,
    FarmerField,
    FieldCrop,
    CropIssue,
    Crop,
    Recommendation,
)
from visits.models import Visit

from .serializers import (
    AdminFarmerSerializer,
    AdminFarmerFieldSerializer,
    AdminFieldCropSerializer,
    AdminVisitSerializer,
    AdminCropIssueSerializer,
    AdminCropSerializer,
    AdminRecommendationSerializer,
)


class ReadOnlyViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    """View-only ViewSet — list + detail, no create/update/delete."""

    pass


# ══════════════════════════════════════════════
# ViewSets
# ══════════════════════════════════════════════


class FarmerViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AdminFarmerSerializer
    queryset = (
        Farmer.objects.select_related("district", "village", "assigned_employee")
        .prefetch_related("fields__crops__crop", "fields__created_by_employee")
        .filter(is_active=True)
        .order_by("-created_at")
    )


class FarmerFieldViewSet(ReadOnlyViewSet):
    """Admin can only view fields. Fields are created by employees during visits."""

    permission_classes = [IsAuthenticated]
    serializer_class = AdminFarmerFieldSerializer
    queryset = (
        FarmerField.objects.select_related("farmer", "created_by_employee")
        .prefetch_related("crops__crop")
        .filter(is_active=True)
        .order_by("-created_at")
    )


class VisitViewSet(ReadOnlyViewSet):
    """Admin can only view visits. Visits are created by employees."""

    permission_classes = [IsAuthenticated]
    serializer_class = AdminVisitSerializer
    queryset = (
        Visit.objects.select_related(
            "employee",
            "employee__employee_profile",
            "district",
            "village",
            "crop",
        )
        .prefetch_related(
            "issues__recommendations__given_by",
            "media_files",
        )
        .order_by("-created_at")
    )
    search_fields = ["farmer_name", "farmer_phone", "employee__username"]
    ordering_fields = ["created_at", "visit_date", "status"]


class CropIssueViewSet(ReadOnlyViewSet):
    """Admin can only view issues. Issues are created by employees."""

    permission_classes = [IsAuthenticated]
    serializer_class = AdminCropIssueSerializer
    queryset = (
        CropIssue.objects.select_related(
            "visit",
            "visit__district",
            "visit__village",
            "visit__employee",
            "visit__employee__employee_profile",
            "crop",
        )
        .prefetch_related("recommendations__given_by")
        .order_by("-created_at")
    )


class CropViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AdminCropSerializer
    queryset = Crop.objects.all().order_by("name_en")

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except Exception as exc:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Error in CropViewSet.list")
            return error_response(
                message="Could not fetch crops.",
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FieldCropViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AdminFieldCropSerializer
    queryset = FieldCrop.objects.select_related("land__farmer", "crop").order_by(
        "-sowing_date"
    )


class RecommendationViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AdminRecommendationSerializer
    queryset = Recommendation.objects.select_related("issue", "given_by").order_by(
        "-created_at"
    )


# ══════════════════════════════════════════════
# Dashboard Stats
# GET /api/v1/dashboard/stats/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Dashboard"],
    summary="Admin dashboard stats",
    description="Returns core admin counters for farmers, fields, visits, and open issues.",
    responses={200: SIMPLE_SUCCESS},
)
class DashboardStatsAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = {
            "farmers": Farmer.objects.filter(is_active=True).count(),
            "fields": FarmerField.objects.filter(is_active=True).count(),
            "visits": Visit.objects.count(),
            "issues_open": CropIssue.objects.filter(status="open").count(),
        }
        return success_response(data=data)
