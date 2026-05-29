import logging

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema
from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from visits.serializers import VisitSerializer, VisitMediaSerializer, VisitMediaUploadSerializer
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE, submitted_visits_qs
from visits.visit_response import build_visit_farmer_block, reload_visit
from visits.querysets import submitted_visits_with_relations
from visits.access import get_visit_for_user
from visits.models import Visit, VisitMedia

logger = logging.getLogger(__name__)


def _visit_timeline(visit: Visit) -> list[dict]:
    """Other submitted visits for the same farmer by this employee (newest first)."""
    if not visit.farmer_id:
        return []
    rows = (
        submitted_visits_qs()
        .filter(employee=visit.employee_id, farmer_id=visit.farmer_id)
        .exclude(pk=visit.pk)
        .order_by("-visit_date", "-created_at")[:20]
    )
    return [
        {
            "id": row.id,
            "visit_date": str(row.visit_date) if row.visit_date else None,
            "crop_id": row.crop_id,
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
        "(farmer, crop, GPS required). Optional multipart `media` files. "
        "Optional `local_sync_id` for offline deduplication."
    ),
    request=VisitSerializer,
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
        serializer = VisitSerializer(visits, many=True, context={"request": request})
        return success_response(data=serializer.data)

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

        visit_serializer = VisitSerializer(
            data=request.data, context={"request": request}
        )
        if not visit_serializer.is_valid():
            return error_response(
                errors=visit_serializer.errors,
                message=SUBMIT_VISIT_REQUIRED_MESSAGE,
            )
        visit = visit_serializer.save(employee=request.user)
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

        media_files = request.FILES.getlist("media")
        media_errors = []
        for file in media_files:
            media_type = request.data.get("media_type", "image")
            media_serializer = VisitMediaUploadSerializer(
                data={"file": file, "media_type": media_type}
            )
            if media_serializer.is_valid():
                media_serializer.save(visit=visit)
            else:
                media_errors.append(media_serializer.errors)
        if media_errors:
            return error_response(
                errors={"media": media_errors}, message="Media upload error"
            )

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
