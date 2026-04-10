import logging

from datetime import timedelta

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

from .models import Visit, VisitAttachment, VisitMedia
from .serializers import VisitSerializer, VisitMediaSerializer, StartVisitSerializer

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Visits"],
    methods=["GET"],
    summary="List visits",
    description="Paginated list of all visits ordered by visit date, newest first. Employees see all visits.",
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
        qs = Visit.objects.select_related("employee", "district", "village").order_by(
            "-visit_date"
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = VisitSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = VisitSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        visit = serializer.save(employee=request.user)
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
        visit = get_object_or_404(Visit, id=visit_id)

        if not request.user.is_staff and visit.employee != request.user:
            return error_response(
                message="Not authorized",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        file = request.FILES.get("file")
        file_type = request.data.get("file_type", "OTHER")

        if not file:
            return error_response(
                message="File required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        attachment = VisitAttachment.objects.create(
            visit=visit,
            file=file,
            file_type=file_type,
        )

        return api_response(
            success=True,
            message="Attachment uploaded",
            data={"file_url": request.build_absolute_uri(attachment.file.url)},
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
        attachment = get_object_or_404(VisitAttachment, id=file_id)

        if not request.user.is_staff and attachment.visit.employee != request.user:
            return error_response(
                message="Not authorized",
                status_code=status.HTTP_403_FORBIDDEN,
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
    description="Returns total, pending, and verified visit counts. Useful for the admin dashboard card.",
    responses={200: SIMPLE_SUCCESS},
)
class VisitStatsAPI(APIView):
    """
    GET /api/visits/stats/
    Returns aggregate visit counts for the admin dashboard.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = Visit.objects.count()
        pending = Visit.objects.filter(status="pending").count()
        verified = Visit.objects.filter(status="verified").count()
        return success_response(
            data={"total": total, "pending": pending, "verified": verified}
        )


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
        visit = get_object_or_404(Visit, id=visit_id)

        if not request.user.is_staff and visit.employee != request.user:
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
#  START VISIT  –  POST /api/v1/visits/start/
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Start a field visit",
    description=(
        "Creates a new visit and immediately sets its status to `active`.  \n"
        "**Required:** `crop` (int), `latitude`, `longitude`  \n"
        "**Optional:** `farmer_name`, `village` (int), `notes`  \n"
        "Returns `visit_id`, `status`, and `start_time`."
    ),
    request=StartVisitSerializer,
    responses={
        201: {
            "description": "Visit started",
            "content": {
                "application/json": {
                    "example": {
                        "visit_id": 42,
                        "status": "active",
                        "start_time": "2026-04-10T09:00:00Z",
                    }
                }
            },
        },
        400: error_schema("StartVisitValidationError"),
    },
)
class StartVisitAPI(APIView):
    """
    Create a new visit and immediately mark it active.

    Required JSON fields: crop (int), latitude (decimal ≤ 6 dp), longitude (decimal ≤ 6 dp)
    Optional: farmer_name, village (int), notes
    Returns: { visit_id, status, start_time }
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        logger.info("StartVisit | user=%s", request.user.username)
        serializer = StartVisitSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return error_response(
                message="Validation failed",
                errors=serializer.errors,
                code="VALIDATION_ERROR",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        now = timezone.now()
        try:
            visit = Visit.objects.create(
                employee=request.user,
                crop=data["crop"],
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
                farmer_name=data.get("farmer_name") or "",
                village=data.get("village"),
                notes=data.get("notes") or "",
                status="active",
                visit_date=now.date(),
                visit_time=now.time(),
            )
        except Exception as exc:
            logger.exception(
                "StartVisit | DB create failed for user=%s: %s",
                request.user.username,
                exc,
            )
            return error_response(
                message="Could not create visit",
                code="SERVER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        logger.info(
            "StartVisit | visit_id=%s created for user=%s",
            visit.id,
            request.user.username,
        )
        return Response(
            {
                "visit_id": visit.id,
                "status": visit.status,
                "start_time": visit.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


# ======================================================
#  ACTIVE VISIT  –  GET /api/v1/visits/active/
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Get active visit",
    description="Returns the currently active visit for the authenticated employee, or `null` if none.",
    responses={200: SIMPLE_SUCCESS},
)
class ActiveVisitAPI(APIView):
    """
    Return the employee's currently active visit (if any).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            visit = (
                Visit.objects.filter(employee=request.user, status="active")
                .select_related("employee", "district", "village")
                .first()
            )
            if not visit:
                return api_response(
                    success=True, message="No active visit", data={"visit": None}
                )
            serializer = VisitSerializer(visit, context={"request": request})
            return api_response(
                success=True, message="Active visit fetched", data=serializer.data
            )
        except Exception as e:
            return api_response(success=False, message=str(e), status=500)


# ======================================================
#  COMPLETE VISIT  –  POST /api/v1/visits/<id>/complete/
# ======================================================
@extend_schema(
    tags=["Visits"],
    summary="Complete a visit",
    description="Marks an active visit as completed. Optionally accepts `notes` in the request body.",
    request={
        "application/json": {
            "type": "object",
            "properties": {"notes": {"type": "string"}},
        }
    },
    responses={200: SIMPLE_SUCCESS, 400: error_schema("CompleteVisitError")},
)
class CompleteVisitAPI(APIView):
    """
    Mark an active visit as completed.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, id):
        visit = get_object_or_404(Visit, id=id)

        if visit.employee != request.user:
            return api_response(
                success=False,
                message="Not authorized",
                status=status.HTTP_403_FORBIDDEN,
            )

        if visit.status == "completed":
            return api_response(
                success=False,
                message="Visit already completed",
                status=status.HTTP_400_BAD_REQUEST,
            )

        visit.status = "completed"
        visit.end_time = timezone.now()
        if request.data.get("notes"):
            visit.notes = request.data["notes"]
        visit.save(update_fields=["status", "end_time", "notes"])

        return api_response(
            success=True,
            message="Visit completed successfully",
            data={
                "visit_id": visit.id,
                "status": visit.status,
                "end_time": visit.end_time.isoformat() if visit.end_time else None,
            },
        )


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

        visit = get_object_or_404(Visit, id=visit_id)

        if not request.user.is_staff and visit.employee != request.user:
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
