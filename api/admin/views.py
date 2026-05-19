from rest_framework import status as http_status
from rest_framework.permissions import IsAdminUser
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.mixins import (
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.viewsets import GenericViewSet
from drf_spectacular.utils import extend_schema
from django.db.models import OuterRef, Prefetch, Subquery

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
from visits.querysets import submitted_visits_with_relations
from visits.submitted import get_visit_cleanup_counts, submitted_visits_qs
from accounts.models import EmployeeProfile

from farmers.audit import build_farmer_visit_audit

from .serializers import (
    AdminFarmerSerializer,
    AdminFarmerFieldSerializer,
    AdminFieldCropSerializer,
    AdminVisitSerializer,
    AdminCropIssueSerializer,
    AdminCropSerializer,
    AdminRecommendationSerializer,
)


def _display_name(user):
    return user.get_full_name() or user.username


def _bounded_int(value, default, minimum=1, maximum=20):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


class AdminPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AdminModelViewSet(ModelViewSet):
    permission_classes = [IsAdminUser]
    pagination_class = AdminPagination


FARMER_ID_FROM_VISIT = Farmer.objects.filter(
    id=OuterRef("visit__farmer_id")
).values("id")[:1]

FARMER_ID_FROM_VISIT_PHONE = Farmer.objects.filter(
    phone=OuterRef("visit__farmer_phone")
).values("id")[:1]

RECOMMENDATION_QS = Recommendation.objects.select_related("given_by").order_by(
    "-created_at"
)

ISSUE_QS = (
    CropIssue.objects.select_related(
        "visit",
        "visit__district",
        "visit__village",
        "visit__employee",
        "visit__employee__employee_profile",
        "visit__farmer",
        "visit__farmer__village",
        "visit__farmer__district",
        "visit__field",
        "crop",
    )
    .annotate(
        admin_farmer_id=Subquery(FARMER_ID_FROM_VISIT),
        admin_farmer_id_by_phone=Subquery(FARMER_ID_FROM_VISIT_PHONE),
    )
    .prefetch_related(Prefetch("recommendations", queryset=RECOMMENDATION_QS))
    .order_by("-created_at")
)


class ReadOnlyViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    """View-only ViewSet — list + detail, no create/update/delete."""

    permission_classes = [IsAdminUser]
    pagination_class = AdminPagination


# ══════════════════════════════════════════════
# ViewSets
# ══════════════════════════════════════════════


class FarmerViewSet(AdminModelViewSet):
    serializer_class = AdminFarmerSerializer
    search_fields = ["farmer_code", "name", "phone", "village__name", "district__name"]
    filterset_fields = ["district", "village", "assigned_employee"]
    ordering_fields = ["created_at", "updated_at", "name", "farmer_code"]
    queryset = (
        Farmer.objects.select_related("district", "village", "assigned_employee")
        .prefetch_related("fields__crops__crop", "fields__created_by_employee")
        .order_by("-created_at")
    )


class FarmerFieldViewSet(ReadOnlyViewSet):
    """Admin can only view fields. Fields are created by employees during visits."""

    serializer_class = AdminFarmerFieldSerializer
    search_fields = ["land_name", "farmer__name", "farmer__phone"]
    filterset_fields = ["farmer", "created_by_employee", "is_active"]
    ordering_fields = ["created_at", "land_name", "land_size"]
    queryset = (
        FarmerField.objects.select_related("farmer", "created_by_employee")
        .prefetch_related("crops__crop")
        .filter(is_active=True)
        .order_by("-created_at")
    )


class VisitViewSet(ReadOnlyViewSet):
    """
    Global admin list: all submitted visits (farmer + crop + GPS on file).
    Not scoped to the logged-in user; optional ?employee= filter only.
    """

    serializer_class = AdminVisitSerializer
    queryset = (
        submitted_visits_with_relations()
        .prefetch_related(
            Prefetch("issues", queryset=ISSUE_QS),
            "media_files",
            "attachments",
            "attachments__uploaded_by",
            "attachments__employee",
        )
        .order_by("-created_at", "-id")
    )
    search_fields = [
        "farmer_name",
        "farmer_phone",
        "farmer__name",
        "farmer__phone",
        "employee__username",
        "employee__first_name",
        "employee__last_name",
        "village__name",
        "crop__name_en",
        "crop__name_ta",
    ]
    filterset_fields = ["employee", "farmer", "field", "district", "village", "crop"]
    ordering_fields = ["created_at", "visit_date", "visit_time"]


class CropIssueViewSet(ReadOnlyViewSet):
    """Admin can only view issues. Issues are created by employees."""

    serializer_class = AdminCropIssueSerializer
    search_fields = [
        "description",
        "visit__farmer_name",
        "visit__farmer_phone",
        "visit__employee__username",
        "crop__name_en",
        "crop__name_ta",
    ]
    filterset_fields = [
        "status",
        "severity",
        "crop",
        "visit__district",
        "visit__village",
    ]
    ordering_fields = ["created_at", "status", "severity"]
    queryset = ISSUE_QS


class CropViewSet(AdminModelViewSet):
    serializer_class = AdminCropSerializer
    search_fields = ["name_en", "name_ta", "scientific_name"]
    filterset_fields = ["is_active", "crop_category", "typical_season"]
    ordering_fields = ["name_en", "created_at"]
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


class FieldCropViewSet(AdminModelViewSet):
    serializer_class = AdminFieldCropSerializer
    search_fields = [
        "crop_name",
        "crop__name_en",
        "land__land_name",
        "land__farmer__name",
    ]
    filterset_fields = ["land", "crop", "is_active", "crop_stage"]
    ordering_fields = ["created_at", "sowing_date", "crop_stage"]
    queryset = FieldCrop.objects.select_related("land__farmer", "crop").order_by(
        "-sowing_date"
    )


class RecommendationViewSet(AdminModelViewSet):
    serializer_class = AdminRecommendationSerializer
    search_fields = ["fertilizer", "pesticide", "dosage", "notes", "issue__description"]
    filterset_fields = ["issue", "given_by"]
    ordering_fields = ["created_at"]
    queryset = RECOMMENDATION_QS.select_related("issue")


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
    permission_classes = [IsAdminUser]

    def get(self, request):
        data = {
            "farmers": Farmer.objects.filter(is_active=True).count(),
            "fields": FarmerField.objects.filter(is_active=True).count(),
            "visits": submitted_visits_qs().count(),
            "issues_open": CropIssue.objects.filter(status="open").count(),
        }
        return success_response(data=data)


@extend_schema(
    tags=["Dashboard"],
    summary="Admin dashboard overview",
    description=(
        "Compact first-load payload for the admin panel: counters, recent visits, "
        "and open issues in one request."
    ),
    responses={200: SIMPLE_SUCCESS},
)
@extend_schema(
    tags=["Admin", "Audit"],
    summary="Farmer vs visit integrity audit",
    description=(
        "Read-only report: farmer/visit counts, orphan visits without farmer FK, "
        "farmers with visit_count, and safe link suggestions (existing Farmer rows only)."
    ),
    responses={200: SIMPLE_SUCCESS},
)
class FarmerVisitAuditAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        orphan_limit = _bounded_int(request.query_params.get("orphan_limit"), 50, maximum=200)
        farmer_limit = _bounded_int(
            request.query_params.get("farmer_limit"), 200, maximum=500
        )
        data = build_farmer_visit_audit(
            orphan_limit=orphan_limit,
            farmer_limit=farmer_limit,
        )
        data["visit_submitted_counts"] = get_visit_cleanup_counts()
        return success_response(data=data)


class DashboardOverviewAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        recent_limit = _bounded_int(request.query_params.get("recent_limit"), 5)
        issues_limit = _bounded_int(request.query_params.get("issues_limit"), 5)

        from visits.submitted import submitted_visits_qs

        stats = {
            "farmers": Farmer.objects.filter(is_active=True).count(),
            "fields": FarmerField.objects.filter(is_active=True).count(),
            "visits": submitted_visits_qs().count(),
            "issues_open": CropIssue.objects.filter(status="open").count(),
            "active_employees": EmployeeProfile.objects.filter(
                is_active_employee=True,
                user__is_active=True,
            ).count(),
        }

        from visits.visit_response import build_visit_employee_block

        recent_visits = []
        for visit in submitted_visits_with_relations().order_by("-created_at")[
            :recent_limit
        ]:
            emp_block = build_visit_employee_block(visit, request)
            recent_visits.append(
                {
                    "id": visit.id,
                    "farmer_name": visit.farmer_name,
                    "farmer_phone": visit.farmer_phone,
                    "visit_date": visit.visit_date,
                    "visit_time": visit.visit_time,
                    "employee_name": _display_name(visit.employee),
                    "employee_profile_photo_url": emp_block.get("profile_photo_url"),
                    "employee_profile_photo_updated_at": emp_block.get(
                        "profile_photo_updated_at"
                    ),
                    "village": visit.village.name if visit.village else None,
                }
            )

        open_issues = [
            {
                "id": issue.id,
                "visit_id": issue.visit_id,
                "severity": issue.severity,
                "status": issue.status,
                "description": issue.description,
                "farmer_name": issue.visit.farmer_name if issue.visit else None,
                "crop_name": issue.crop.name_en if issue.crop else None,
                "created_at": issue.created_at,
            }
            for issue in ISSUE_QS.filter(status="open")[:issues_limit]
        ]

        return success_response(
            data={
                "stats": stats,
                "recent_visits": recent_visits,
                "open_issues": open_issues,
            }
        )
