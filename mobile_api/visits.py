import logging

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.pagination import StandardPagination
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from visits.serializers import VisitSerializer, VisitMediaSerializer, VisitMediaUploadSerializer
from visits.field_visit_serializers import FieldVisitSubmitSerializer
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE, submitted_visits_qs
from visits.visit_response import build_visit_farmer_block, reload_visit
from visits.querysets import submitted_visits_with_relations
from visits.access import get_visit_for_user
from visits.models import Visit, VisitMedia
from visits.date_filters import apply_visit_date_filter
from visits.visit_media import attach_visit_media_files

logger = logging.getLogger(__name__)


def _visit_timeline(visit: Visit) -> list[dict]:
    """Other submitted visits for the same farmer by this employee (newest first)."""
    if not visit.farmer_id:
        return []
    from visits.field_notes import resolved_recommendation, stored_observation
    from visits.visit_response import build_field_visit_problem_block, crop_display_name

    rows = (
        submitted_visits_qs()
        .filter(employee=visit.employee_id, farmer_id=visit.farmer_id)
        .exclude(pk=visit.pk)
        .select_related("crop", "problem_category", "problem_master")
        .order_by("-visit_date", "-created_at")[:20]
    )
    return [
        {
            "id": row.id,
            "visit_date": str(row.visit_date) if row.visit_date else None,
            "crop_id": row.crop_id,
            "crop_name": crop_display_name(row),
            "problem_category_id": row.problem_category_id,
            "problem_item_id": row.problem_master_id,
            "recommendation": resolved_recommendation(row) or None,
            "observation": stored_observation(row) or None,
            "action_taken": row.action_taken or None,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Mobile visits list/create",
    description=(
        "GET: employee's submitted visits. POST: one-shot visit submit "
        "(field visit form or legacy farmer+crop+GPS). Optional multipart `media` files. "
        "Optional `local_sync_id` for offline deduplication."
    ),
    parameters=[
        OpenApiParameter(
            "date_filter",
            OpenApiTypes.STR,
            description="Filter by visit date: `today`, `week` (Mon–today), `month` (1st–today).",
        ),
    ],
    request=FieldVisitSubmitSerializer,
    responses={
        200: VisitSerializer(many=True),
        201: VisitSerializer,
        400: error_schema("MobileVisitValidationError"),
    },
)
class MobileVisitListCreateAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        user = request.user
        visits = (
            submitted_visits_with_relations()
            .filter(employee=user)
            .order_by("-created_at", "-id")
        )
        date_filter = request.query_params.get("date_filter")
        visits = apply_visit_date_filter(visits, date_filter)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(visits, request)
        serializer = VisitSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        sync_id = (request.data.get("local_sync_id") or "").strip()
        if sync_id:
            existing = Visit.objects.filter(
                employee=request.user, local_sync_id=sync_id
            ).first()
            if existing:
                visit = reload_visit(existing.pk)
                return success_response(
                    data={
                        "visit_id": visit.id,
                        "visit": VisitSerializer(
                            visit, context={"request": request}
                        ).data,
                        "farmer": build_visit_farmer_block(visit),
                        "duplicate": True,
                    },
                    message="Visit already synced",
                )

        visit_serializer = FieldVisitSubmitSerializer(
            data=request.data, context={"request": request}
        )
        if not visit_serializer.is_valid():
            return error_response(
                errors=visit_serializer.errors,
                message=SUBMIT_VISIT_REQUIRED_MESSAGE,
            )
        visit = visit_serializer.save()
        media_error = attach_visit_media_files(request, visit)
        if media_error:
            return media_error
        visit = reload_visit(visit.pk)

        logger.info(
            "MobileVisitCreate employee_id=%s farmer_id=%s visit_id=%s sync_id=%s",
            request.user.pk,
            visit.farmer_id,
            visit.id,
            sync_id or None,
        )

        try:
            from dashboard.services import invalidate_dashboard_caches

            invalidate_dashboard_caches()
        except Exception:
            logger.debug("Dashboard cache invalidation skipped", exc_info=True)

        visit_data = VisitSerializer(visit, context={"request": request}).data
        farmer_block = build_visit_farmer_block(visit)
        return success_response(
            data={
                "visit_id": visit.id,
                "visit": visit_data,
                "farmer": farmer_block,
                "duplicate": False,
            },
            message="Visit created",
        )


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Mobile visit detail",
    description="Submitted visit detail plus farmer visit timeline for the employee.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("VisitNotFound")},
)
class MobileVisitDetailAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request, pk):
        visit = get_object_or_404(
            submitted_visits_with_relations().filter(employee=request.user),
            pk=pk,
        )
        data = VisitSerializer(visit, context={"request": request}).data
        data["timeline"] = _visit_timeline(visit)
        return success_response(data=data, message="Visit fetched")

    def patch(self, request, pk):
        visit = get_object_or_404(
            submitted_visits_with_relations().filter(employee=request.user),
            pk=pk,
        )
        serializer = VisitSerializer(
            visit,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                message="Validation failed",
            )
        visit = serializer.save()
        visit = reload_visit(visit.pk)
        return success_response(
            data=VisitSerializer(visit, context={"request": request}).data,
            message="Visit updated",
        )


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Upload visit media (mobile)",
    description="Attach photo/bill/audio/video to an existing visit owned by the employee.",
    request=VisitMediaUploadSerializer,
    responses={201: SIMPLE_SUCCESS, 400: error_schema("MediaUploadError")},
)
class MobileVisitMediaUploadAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        visit = get_visit_for_user(request.user, pk)
        if visit.employee_id != request.user.id:
            return error_response(message="Not authorized", status_code=403)

        file = request.FILES.get("file")
        if not file:
            media_files = request.FILES.getlist("media")
            file = media_files[0] if media_files else None
        if not file:
            return error_response(message="file is required", status_code=400)

        media_type = (request.data.get("media_type") or "image").strip().lower()
        valid_types = {c[0] for c in VisitMedia.MEDIA_TYPE_CHOICES}
        if media_type not in valid_types:
            return error_response(
                message=f"media_type must be one of: {', '.join(sorted(valid_types))}",
                status_code=400,
            )

        media_errors = validate_visit_media_file(file_obj=file, media_type=media_type)
        if media_errors:
            return error_response(
                message=media_errors.get("file")
                or media_errors.get("media_type", "Invalid media file."),
                status_code=400,
            )

        media = VisitMedia.objects.create(
            visit=visit,
            file=file,
            media_type=media_type,
            caption=request.data.get("caption", ""),
        )
        return success_response(
            data=VisitMediaSerializer(media, context={"request": request}).data,
            message="Media uploaded",
        )
