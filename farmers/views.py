from django.shortcuts import get_object_or_404
from django.db.models import Q

from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.response import (
    success_response,
    error_response,
    forbidden_response,
    created_response,
)
from utils.schema import (
    PAGINATION_PARAMS,
    SEARCH_PARAM,
    SIMPLE_SUCCESS,
    error_schema,
    IS_ACTIVE_PARAM,
)

from masters.models import (
    Farmer,
    FarmerField,
    FieldCrop,
    CropIssue,
    Recommendation,
    Crop,
    FarmerActivity,
)
from visits.models import Visit, VisitMedia
from visits.serializers import (
    VisitMediaSerializer,
    VisitSerializer as BaseVisitSerializer,
)

from .permissions import IsAdminOnly
from .serializers import (
    FarmerListSerializer,
    FarmerDetailSerializer,
    FarmerCreateSerializer,
    FarmerUpdateSerializer,
    FarmerFieldSerializer,
    FarmerFieldCreateSerializer,
    FieldCropSerializer,
    FieldCropCreateSerializer,
    CropIssueSerializer,
    CropIssueCreateSerializer,
    RecommendationSerializer,
    RecommendationCreateSerializer,
    FarmerVisitSerializer,
    FarmerActivitySerializer,
    CropMasterSerializer,
    CropMasterCreateSerializer,
)


# ══════════════════════════════════════════════
# PAGINATION
# ══════════════════════════════════════════════


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ══════════════════════════════════════════════
# FARMERS
# GET  /api/v1/farmers/
# POST /api/v1/farmers/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Farmers"],
    methods=["GET"],
    summary="List farmers",
    request=CropMasterCreateSerializer,
    description="Paginated list of active farmers with their fields and crops. Searchable by name or phone.",
    parameters=[*PAGINATION_PARAMS, SEARCH_PARAM],
    responses={200: FarmerListSerializer(many=True)},
)
@extend_schema(
    tags=["Farmers"],
    methods=["POST"],
    summary="Create farmer",
    description="Register a new farmer. Only field employees can create farmers (admin access is blocked).",
    request=FarmerCreateSerializer,
    responses={201: FarmerListSerializer, 403: error_schema("FarmerForbidden")},
)
class FarmerListCreateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        farmers = (
            Farmer.objects.select_related("district", "village", "assigned_employee")
            .prefetch_related("fields__crops__crop")
            .filter(is_active=True)
            .order_by("name")
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(farmers, request)
        serializer = FarmerListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot create farmers. Employee access only."
            )
        serializer = FarmerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        farmer = serializer.save(created_by_employee=request.user)
        return created_response(
            data=FarmerListSerializer(farmer, context={"request": request}).data
        )


# ══════════════════════════════════════════════
# FARMER DETAIL
# GET  /api/v1/farmers/{id}/
# PUT  /api/v1/farmers/{id}/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Farmers"],
    methods=["GET"],
    summary="Farmer detail",
    description="Full farmer profile including fields and crop history.",
    responses={200: FarmerDetailSerializer, 404: error_schema("FarmerNotFound")},
)
@extend_schema(
    tags=["Farmers"],
    methods=["PUT"],
    summary="Update farmer",
    description="Partial update (PATCH behaviour) of farmer profile. Employee access only.",
    request=FarmerUpdateSerializer,
    responses={200: FarmerDetailSerializer, 403: error_schema("FarmerUpdateForbidden")},
)
class FarmerDetailAPI(APIView):
    permission_classes = [IsAuthenticated]

    def _get_farmer(self, pk):
        return get_object_or_404(
            Farmer.objects.select_related(
                "village", "district", "assigned_employee"
            ).prefetch_related(
                "fields__crops__crop",
            ),
            pk=pk,
            is_active=True,
        )

    def get(self, request, pk):
        farmer = self._get_farmer(pk)
        serializer = FarmerDetailSerializer(farmer, context={"request": request})
        return success_response(data=serializer.data)

    def put(self, request, pk):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot edit farmers. Employee access only."
            )
        farmer = self._get_farmer(pk)
        serializer = FarmerUpdateSerializer(farmer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        farmer.refresh_from_db()
        return success_response(
            data=FarmerDetailSerializer(farmer, context={"request": request}).data
        )


# ══════════════════════════════════════════════
# FARMER FIELDS
# GET  /api/v1/farmers/{id}/fields/
# POST /api/v1/farmers/{id}/fields/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Farmers"],
    methods=["GET"],
    summary="List farmer fields",
    description="List all active fields belonging to a farmer.",
    responses={200: FarmerFieldSerializer(many=True)},
)
@extend_schema(
    tags=["Farmers"],
    methods=["POST"],
    summary="Add farmer field",
    description="Create a new agricultural field under a farmer. Employee access only.",
    request=FarmerFieldCreateSerializer,
    responses={201: FarmerFieldSerializer},
)
class FarmerFieldListCreateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, farmer_id):
        farmer = get_object_or_404(Farmer, pk=farmer_id, is_active=True)
        fields = (
            FarmerField.objects.filter(farmer=farmer, is_active=True)
            .prefetch_related("crops__crop")
            .order_by("field_name")
        )
        serializer = FarmerFieldSerializer(
            fields, many=True, context={"request": request}
        )
        return success_response(data=serializer.data)

    def post(self, request, farmer_id):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot create fields. Employee access only."
            )
        farmer = get_object_or_404(Farmer, pk=farmer_id, is_active=True)
        serializer = FarmerFieldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field = serializer.save(farmer=farmer, created_by_employee=request.user)
        return created_response(
            data=FarmerFieldSerializer(field, context={"request": request}).data
        )


# ══════════════════════════════════════════════
# FIELD CROPS
# POST /api/v1/fields/{field_id}/crops/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Farmers"],
    summary="Add crop to farmer field",
    description="Associates a crop with a specific farmer field. Employee access only.",
    request=FieldCropCreateSerializer,
    responses={201: FieldCropSerializer, 403: error_schema("FieldCropForbidden")},
)
class FieldCropCreateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, field_id):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot add crops. Employee access only."
            )
        field = get_object_or_404(FarmerField, pk=field_id, is_active=True)
        serializer = FieldCropCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crop = serializer.save(land=field)
        return created_response(
            data=FieldCropSerializer(crop, context={"request": request}).data
        )


# ══════════════════════════════════════════════
# VISITS (farmer-centric)
# GET  /api/v1/visits/             → all visits (paginated)
# POST /api/v1/visits/             → create visit
# GET  /api/v1/farmers/{id}/visits/ → visits for a farmer
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Visits"],
    summary="List all visits or create a visit",
    description="GET: paginated list of visits with search and date range filters. POST: create a new visit (employee only).",
    parameters=PAGINATION_PARAMS
    + [
        SEARCH_PARAM,
        OpenApiParameter(
            "date_from",
            OpenApiTypes.DATE,
            description="Filter visits from this date (YYYY-MM-DD)",
        ),
        OpenApiParameter(
            "date_to",
            OpenApiTypes.DATE,
            description="Filter visits up to this date (YYYY-MM-DD)",
        ),
    ],
    responses={200: FarmerVisitSerializer(many=True), 201: FarmerVisitSerializer},
)
class VisitListCreateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            Visit.objects.select_related(
                "farmer",
                "farmer__village",
                "farmer__village__district",
                "field",
                "employee",
                "employee__employee_profile",
                "crop",
            )
            .prefetch_related(
                "media_files",
                "issues__recommendations__given_by",
            )
            .order_by("-visit_date")
        )

        params = request.query_params

        # Text search across farmer, village, field, employee, crop
        search = params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(farmer__name__icontains=search)
                | Q(farmer_name__icontains=search)
                | Q(farmer__village__name__icontains=search)
                | Q(field__field_name__icontains=search)
                | Q(employee__username__icontains=search)
                | Q(crop__name_en__icontains=search)
            )

        # Date range
        date_from = params.get("date_from", "").strip()
        if date_from:
            qs = qs.filter(visit_date__gte=date_from)

        date_to = params.get("date_to", "").strip()
        if date_to:
            qs = qs.filter(visit_date__lte=date_to)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = FarmerVisitSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot create visits. Employee access only."
            )
        serializer = BaseVisitSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        visit = serializer.save(employee=request.user)
        return created_response(
            data=FarmerVisitSerializer(visit, context={"request": request}).data
        )


@extend_schema(
    tags=["Visits"],
    summary="List visits for a farmer",
    description="Returns paginated visit history for the specified farmer.",
    parameters=PAGINATION_PARAMS,
    responses={
        200: FarmerVisitSerializer(many=True),
        404: error_schema("FarmerVisitNotFound"),
    },
)
class FarmerVisitListAPI(APIView):
    """GET /api/v1/farmers/{id}/visits/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, farmer_id):
        farmer = get_object_or_404(Farmer, pk=farmer_id, is_active=True)
        visits = (
            Visit.objects.filter(farmer=farmer)
            .select_related("employee")
            .prefetch_related(
                "media_files",
                "issues__crop",
                "issues__recommendations",
            )
            .order_by("-visit_date")
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(visits, request)
        serializer = FarmerVisitSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)


# ══════════════════════════════════════════════
# CROP ISSUES
# POST /api/v1/visits/{id}/issues/
# GET  /api/v1/issues/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Crop Issues"],
    summary="Report crop issue for a visit",
    description="Creates a new crop issue linked to a visit. Employee access only.",
    request=CropIssueCreateSerializer,
    responses={201: CropIssueSerializer, 403: error_schema("IssueForbidden")},
)
class VisitIssueCreateAPI(APIView):
    """POST /api/v1/visits/{visit_id}/issues/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, visit_id):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot report issues. Employee access only."
            )
        visit = get_object_or_404(Visit, pk=visit_id)
        serializer = CropIssueCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue = serializer.save(visit=visit)
        return created_response(
            data=CropIssueSerializer(issue, context={"request": request}).data
        )


@extend_schema(
    tags=["Crop Issues"],
    summary="List crop issues",
    description="Paginated list of all crop issues. Filterable by severity and farmer.",
    parameters=PAGINATION_PARAMS
    + [
        OpenApiParameter(
            "severity",
            OpenApiTypes.STR,
            description="Filter by severity (low/medium/high/critical)",
        ),
        OpenApiParameter("farmer", OpenApiTypes.INT, description="Filter by farmer ID"),
    ],
    responses={200: CropIssueSerializer(many=True)},
)
class CropIssueListAPI(APIView):
    """GET /api/v1/issues/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            CropIssue.objects.select_related(
                "visit",
                "visit__employee",
                "visit__employee__employee_profile",
                "visit__district",
                "visit__village",
                "crop",
            )
            .prefetch_related("recommendations__given_by")
            .order_by("-created_at")
        )

        severity = request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)

        farmer_id = request.query_params.get("farmer")
        if farmer_id:
            try:
                farmer = Farmer.objects.only("phone").get(pk=farmer_id)
                qs = qs.filter(visit__farmer_phone=farmer.phone)
            except Farmer.DoesNotExist:
                qs = qs.none()

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = CropIssueSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


# ══════════════════════════════════════════════
# VISIT MEDIA
# POST /api/v1/visits/{id}/media/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Visits"],
    summary="Upload visit media",
    description="Uploads a media file (image/video) linked to a visit. Employee access only. Use multipart/form-data.",
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "media_type": {"type": "string"},
            },
            "required": ["file", "media_type"],
        }
    },
    responses={
        201: VisitMediaSerializer,
        400: error_schema("MediaUploadError"),
        403: error_schema("MediaForbidden"),
    },
)
class VisitMediaUploadAPI(APIView):
    """POST /api/v1/visits/{visit_id}/media/"""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, visit_id):
        if request.user.is_staff:
            return forbidden_response(
                "Admin users cannot upload media. Employee access only."
            )
        visit = get_object_or_404(Visit, pk=visit_id)

        if visit.employee != request.user:
            return forbidden_response("Not authorized")

        file = request.FILES.get("file")
        media_type = request.data.get("media_type", "").strip().lower()

        if not file:
            return error_response(
                message="file is required.", status_code=status.HTTP_400_BAD_REQUEST
            )

        valid_types = {c[0] for c in VisitMedia.MEDIA_TYPE_CHOICES}
        if media_type not in valid_types:
            return error_response(
                message=f"media_type must be one of: {', '.join(sorted(valid_types))}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        media = VisitMedia.objects.create(visit=visit, file=file, media_type=media_type)
        return created_response(
            data=VisitMediaSerializer(media, context={"request": request}).data
        )


# ══════════════════════════════════════════════
# FARMER ACTIVITY TIMELINE
# GET /api/v1/farmers/{id}/activity/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Farmers"],
    summary="Farmer activity timeline",
    description="Returns paginated activity timeline for the specified farmer.",
    parameters=PAGINATION_PARAMS
    + [
        OpenApiParameter(
            "activity_type", OpenApiTypes.STR, description="Filter by activity type"
        ),
    ],
    responses={
        200: FarmerActivitySerializer(many=True),
        404: error_schema("FarmerActivityNotFound"),
    },
)
class FarmerActivityListAPI(APIView):
    """GET /api/v1/farmers/{farmer_id}/activity/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, farmer_id):
        farmer = get_object_or_404(Farmer, pk=farmer_id, is_active=True)
        qs = (
            FarmerActivity.objects.filter(farmer=farmer)
            .select_related("created_by")
            .order_by("-created_at")
        )

        activity_type = request.query_params.get("activity_type")
        if activity_type:
            qs = qs.filter(activity_type=activity_type)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = FarmerActivitySerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)


# ══════════════════════════════════════════════
# CROP MASTER (expanded catalog)
# GET  /api/v1/crops/
# POST /api/v1/crops/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Masters"],
    summary="List or create crop master records",
    description="GET: paginated list of active crops with search, category, and season filters. POST: admin-only create.",
    request=CropMasterCreateSerializer,
    parameters=PAGINATION_PARAMS
    + [
        SEARCH_PARAM,
        OpenApiParameter(
            "crop_category", OpenApiTypes.STR, description="Filter by crop category"
        ),
        OpenApiParameter(
            "typical_season", OpenApiTypes.STR, description="Filter by typical season"
        ),
    ],
    responses={200: CropMasterSerializer(many=True), 201: CropMasterSerializer},
)
class CropMasterListCreateAPI(APIView):
    """GET/POST /api/v1/crops/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Crop.objects.filter(is_active=True).order_by("name_en")

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(name_en__icontains=search)
                | Q(name_ta__icontains=search)
                | Q(scientific_name__icontains=search)
            )

        category = request.query_params.get("crop_category")
        if category:
            qs = qs.filter(crop_category=category)

        season = request.query_params.get("typical_season")
        if season:
            qs = qs.filter(typical_season=season)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = CropMasterSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if not request.user.is_staff:
            return forbidden_response("Admin access required.")
        serializer = CropMasterCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crop = serializer.save()
        return created_response(
            data=CropMasterSerializer(crop, context={"request": request}).data
        )


# ══════════════════════════════════════════════
# RECOMMENDATIONS (Admin only)
# POST /api/v1/issues/{issue_id}/recommendations/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Visits"],
    summary="Create recommendation for a crop issue",
    description="Admin-only endpoint to add an agronomic recommendation to a reported crop issue.",
    request=RecommendationCreateSerializer,
    responses={
        201: RecommendationSerializer,
        403: error_schema("RecommendationForbidden"),
    },
)
class RecommendationCreateAPI(APIView):
    """
    POST /api/v1/issues/{issue_id}/recommendations/
    Admin-only: provide a recommendation for a crop issue.
    """

    permission_classes = [IsAdminOnly]

    def post(self, request, issue_id):
        issue = get_object_or_404(CropIssue, pk=issue_id)
        serializer = RecommendationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recommendation = serializer.save(issue=issue, given_by=request.user)
        return created_response(
            data=RecommendationSerializer(
                recommendation, context={"request": request}
            ).data
        )


@extend_schema(
    tags=["Crop Issues"],
    summary="Recommend and resolve issue",
    description="Adds a recommendation to a crop issue and marks the issue as resolved.",
    request=RecommendationCreateSerializer,
    responses={200: SIMPLE_SUCCESS, 403: error_schema("RecommendationForbidden")},
)
class RecommendIssueAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, issue_id):
        if not request.user.is_staff:
            return forbidden_response("Admin access required.")

        issue = get_object_or_404(CropIssue, id=issue_id)

        serializer = RecommendationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        recommendation = serializer.save(
            issue=issue,
            given_by=request.user,
        )

        issue.status = "resolved"
        issue.save(update_fields=["status"])

        return success_response(
            message="Recommendation added and issue resolved",
            data={
                "issue_id": issue.id,
                "recommendation_id": recommendation.id,
                "status": issue.status,
            },
        )


# ══════════════════════════════════════════════
# TRACKING (thin wrappers — existing views already handle logic)
# POST /api/v1/tracking/workday/start/
# POST /api/v1/tracking/workday/end/
# POST /api/v1/tracking/location/push/
# GET  /api/v1/tracking/admin/geo/employees/
#
# These are already served by tracking app URLs and are re-exported
# in farmers/urls.py via include(). No duplicate code needed.
# ══════════════════════════════════════════════
