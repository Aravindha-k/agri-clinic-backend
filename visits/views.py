import logging

from datetime import timedelta

from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.response import api_response, success_response, error_response
from utils.schema import PAGINATION_PARAMS, SIMPLE_SUCCESS, error_schema

from .access import get_visit_for_user, is_privileged_user
from .querysets import submitted_visits_with_relations
from .models import Visit, VisitAttachment, VisitMedia
from .serializers import VisitSerializer, VisitMediaSerializer
from .submitted import SUBMIT_VISIT_REQUIRED_MESSAGE

logger = logging.getLogger(__name__)


def _invalidate_dashboard_cache():
    try:
        from dashboard.services import invalidate_stats_cache

        invalidate_stats_cache()
    except Exception:
        logger.debug("Dashboard cache invalidation skipped", exc_info=True)


def _invalidate_visit_caches():
    _invalidate_dashboard_cache()
    try:
        from farmers.services import invalidate_farmers_list_cache

        invalidate_farmers_list_cache()
    except Exception:
        logger.debug("Farmers list cache invalidation skipped", exc_info=True)


@extend_schema(
    tags=["Visits"],
    methods=["GET"],
    summary="List visits",
    description="Paginated list of visits ordered by visit date, newest first. Admins see all visits; employees see their own visits.",
    parameters=[*PAGINATION_PARAMS],
    responses={200: VisitSerializer(many=True)},
)
@extend_schema(
    tags=["Visits"],
    methods=["POST"],
    summary="Create visit",
    description="Create a new field visit. Media files can be attached as multipart `media_files[]`.",
    request=VisitSerializer,
    responses={201: SIMPLE_SUCCESS, 400: error_schema("VisitCreateError")},
)
class VisitListCreateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = submitted_visits_with_relations().order_by("-created_at", "-id")
        if not is_privileged_user(request.user):
            qs = qs.filter(employee=request.user)

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(farmer_name__icontains=search)
                | Q(farmer_phone__icontains=search)
                | Q(farmer__name__icontains=search)
                | Q(farmer__phone__icontains=search)
                | Q(employee__username__icontains=search)
                | Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(village__name__icontains=search)
                | Q(crop__name_en__icontains=search)
            )

        paginator = VisitListPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = VisitSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = VisitSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        visit = serializer.save(employee=request.user)
        _invalidate_visit_caches()
        files = (
            request.FILES.getlist("media_files") if hasattr(request, "FILES") else []
        )
        for file in files:
            media_type = (
                "image"
                if file.content_type.startswith("image")
                else "video" if file.content_type.startswith("video") else "other"
            )
            VisitMedia.objects.create(visit=visit, file=file, media_type=media_type)
        return api_response(
            success=True,
            message="Visit created successfully",
            data={"visit_id": visit.id, "visit_date": str(visit.created_at)},
            status=status.HTTP_201_CREATED,
        )


# ══════════════════════════════════════════════
# BULK VISIT UPLOAD (Offline Sync)
# POST /api/v1/visits/bulk/
# ══════════════════════════════════════════════


@extend_schema(
    tags=["Visits"],
    summary="Bulk visit upload (offline sync)",
    description="Upload a batch of visits collected offline. Returns list of created IDs and any per-item errors.",
    request={
        "application/json": {
            "type": "object",
            "properties": {"visits": {"type": "array", "items": {"type": "object"}}},
            "required": ["visits"],
        }
    },
    responses={201: SIMPLE_SUCCESS, 207: SIMPLE_SUCCESS},
)
class BulkVisitUploadAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Expecting a list of visit dicts in request.data["visits"]
        visits_data = request.data.get("visits", [])
        created = []
        errors = []
        for vdata in visits_data:
            serializer = VisitSerializer(data=vdata, context={"request": request})
            if serializer.is_valid():
                visit = serializer.save(employee=request.user)
                created.append(visit.id)
            else:
                errors.append(serializer.errors)
        # Ensure errors is always a list
        if errors is None:
            errors = []
        return api_response(
            success=len(errors) == 0,
            message="Bulk visits upload complete",
            data={"created": created, "errors": errors},
            status=(
                status.HTTP_201_CREATED
                if len(errors) == 0
                else status.HTTP_207_MULTI_STATUS
            ),
        )


# ══════════════════════════════════════════════
# PAGINATION
# ══════════════════════════════════════════════
class VisitListPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ======================================================
# EMPLOYEE: UPLOAD ATTACHMENT
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Upload visit attachment",
    description="Upload a file attachment to a specific visit. Multipart form upload.",
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "file_type": {"type": "string", "example": "PHOTO"},
            },
        }
    },
    responses={201: SIMPLE_SUCCESS, 403: error_schema("AttachmentForbidden")},
)
class VisitAttachmentUploadAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, visit_id):
        visit = get_visit_for_user(request.user, visit_id)

        if not is_privileged_user(request.user) and visit.employee != request.user:
            return error_response(
                message="Not authorized",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        from visits.attachment_serializers import (
            VisitAttachmentCreateSerializer,
            VisitAttachmentSerializer,
        )

        serializer = VisitAttachmentCreateSerializer(
            data={
                "attachment_type": request.data.get("attachment_type")
                or request.data.get("file_type", "other"),
                "file": request.FILES.get("file"),
                "text_content": request.data.get("text_content"),
            },
            context={"request": request, "visit": visit},
        )
        if not serializer.is_valid():
            return error_response(
                message="Validation failed",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        attachment = serializer.save()
        return api_response(
            success=True,
            message="Attachment uploaded",
            data=VisitAttachmentSerializer(
                attachment, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


# ======================================================
# DOWNLOAD ATTACHMENT
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Download visit attachment",
    description="Download a previously uploaded visit attachment file.",
    responses={
        200: {"description": "File download"},
        403: error_schema("DownloadForbidden"),
    },
)
class VisitAttachmentDownloadAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, file_id):
        attachment = get_object_or_404(
            VisitAttachment.objects.filter(visit__in=visits_for_user(request.user)),
            id=file_id,
        )

        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.file.name.split("/")[-1],
        )


# ======================================================
#  VISIT STATS (Admin Dashboard)
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Visit stats",
    description="Returns submitted visit count (farmer, crop, GPS on file).",
    responses={200: SIMPLE_SUCCESS},
)
class VisitStatsAPI(APIView):
    """GET /api/visits/stats/ — submitted visits only."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = submitted_visits_with_relations()
        if not is_privileged_user(request.user):
            qs = qs.filter(employee=request.user)
        total = qs.count()
        return success_response(data={"total": total, "submitted": total})


# ======================================================
#  VISIT MEDIA UPLOAD
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Upload visit media",
    description="Upload an image, audio, video, or bill file to a visit. `media_type` must be one of the supported types.",
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "media_type": {"type": "string", "example": "image"},
                "caption": {"type": "string"},
            },
        }
    },
    responses={201: SIMPLE_SUCCESS, 400: error_schema("MediaUploadError")},
)
class VisitMediaUploadAPIView(APIView):
    """
    POST /api/v1/visits/<visit_id>/upload-media/
    Upload media (image, bill, audio, video) to a visit.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, visit_id):
        visit = get_visit_for_user(request.user, visit_id)

        if not is_privileged_user(request.user) and visit.employee != request.user:
            return error_response(
                message="Not authorized",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        file = request.FILES.get("file")
        media_type = request.data.get("media_type", "").strip().lower()
        caption = request.data.get("caption", "")

        if not file:
            return error_response(
                message="file is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        valid_types = {c[0] for c in VisitMedia.MEDIA_TYPE_CHOICES}
        if media_type not in valid_types:
            return error_response(
                message=f"media_type must be one of: {', '.join(sorted(valid_types))}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        media = VisitMedia.objects.create(
            visit=visit,
            file=file,
            media_type=media_type,
            caption=caption,
        )

        return api_response(
            success=True,
            message="Media uploaded",
            data=VisitMediaSerializer(media, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ======================================================
#  Deprecated draft visit flow (start / active / complete)
# ======================================================
_VISIT_DRAFT_REMOVED_MESSAGE = (
    "Draft visits are no longer supported. Submit a complete visit in one request "
    f"to POST /api/v1/visits/ or POST /api/v1/mobile/visits/. {SUBMIT_VISIT_REQUIRED_MESSAGE}"
)


class _DeprecatedVisitFlowAPI(APIView):
    permission_classes = [IsAuthenticated]

    def _gone(self):
        return error_response(
            message=_VISIT_DRAFT_REMOVED_MESSAGE,
            code="VISIT_FLOW_DEPRECATED",
            status_code=status.HTTP_410_GONE,
        )


@extend_schema(
    tags=["Visits"],
    summary="(Deprecated) Start visit",
    deprecated=True,
    responses={410: error_schema("VisitFlowDeprecated")},
)
class StartVisitAPI(_DeprecatedVisitFlowAPI):
    def post(self, request):
        return self._gone()


@extend_schema(
    tags=["Visits"],
    summary="(Deprecated) Active visit",
    deprecated=True,
    responses={410: error_schema("VisitFlowDeprecated")},
)
class ActiveVisitAPI(_DeprecatedVisitFlowAPI):
    def get(self, request):
        return self._gone()


@extend_schema(
    tags=["Visits"],
    summary="(Deprecated) Complete visit",
    deprecated=True,
    responses={410: error_schema("VisitFlowDeprecated")},
)
class CompleteVisitAPI(_DeprecatedVisitFlowAPI):
    def post(self, request, id):
        return self._gone()


# ======================================================
#  UPLOAD PHOTO  –  POST /api/v1/visits/upload-photo/
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Upload visit photo",
    description="Upload a photo for a visit. Multipart: `visit_id` (int) + `image` (file).",
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "visit_id": {"type": "integer"},
                "image": {"type": "string", "format": "binary"},
            },
            "required": ["visit_id", "image"],
        }
    },
    responses={201: SIMPLE_SUCCESS, 400: error_schema("PhotoUploadError")},
)
class VisitPhotoUploadAPI(APIView):
    """
    Upload a photo for a visit.
    Multipart: visit_id (int) + image (file).
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        visit_id = request.data.get("visit_id")
        if not visit_id:
            return api_response(
                success=False,
                message="visit_id is required",
                status=status.HTTP_400_BAD_REQUEST,
            )

        visit = get_visit_for_user(request.user, visit_id)

        if not is_privileged_user(request.user) and visit.employee != request.user:
            return api_response(
                success=False,
                message="Not authorized",
                status=status.HTTP_403_FORBIDDEN,
            )

        image = request.FILES.get("image")
        if not image:
            return api_response(
                success=False,
                message="image file is required",
                status=status.HTTP_400_BAD_REQUEST,
            )

        media = VisitMedia.objects.create(
            visit=visit,
            file=image,
            media_type="image",
        )

        return api_response(
            success=True,
            message="Photo uploaded",
            data=VisitMediaSerializer(media, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
