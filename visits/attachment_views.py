import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from mobile_api.device_session import DeviceSessionRequiredMixin
from api.admin.permissions import IsAdminUser
from utils.response import created_response, error_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from visits.access import get_visit_for_user, is_privileged_user
from visits.attachment_serializers import (
    VisitAttachmentCreateSerializer,
    VisitAttachmentSerializer,
)
from visits.models import Visit, VisitAttachment

logger = logging.getLogger(__name__)


def _invalidate_visit_caches():
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception:
        logger.debug("Dashboard cache invalidation skipped", exc_info=True)


def _attachments_for_visit(visit):
    return (
        VisitAttachment.objects.filter(visit=visit)
        .select_related("employee", "uploaded_by", "visit")
        .order_by("-uploaded_at", "-id")
    )


def _serialize_list(request, queryset):
    data = VisitAttachmentSerializer(
        queryset, many=True, context={"request": request}
    ).data
    return success_response(data=data, message="Attachments fetched")


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="List visit attachments (mobile)",
    responses={200: SIMPLE_SUCCESS, 403: error_schema("Forbidden")},
)
class MobileVisitAttachmentListCreateAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, visit_id):
        visit = get_visit_for_user(request.user, visit_id)
        if visit.employee_id != request.user.id and not is_privileged_user(request.user):
            return error_response(message="Not authorized", status_code=403)
        return _serialize_list(request, _attachments_for_visit(visit))

    def post(self, request, visit_id):
        visit = get_visit_for_user(request.user, visit_id)
        if visit.employee_id != request.user.id:
            return error_response(message="Not authorized", status_code=403)

        serializer = VisitAttachmentCreateSerializer(
            data=request.data,
            context={"request": request, "visit": visit},
        )
        if not serializer.is_valid():
            return error_response(
                message="Validation failed",
                errors=serializer.errors,
                status_code=400,
            )

        attachment = serializer.save()
        _invalidate_visit_caches()
        return created_response(
            data=VisitAttachmentSerializer(
                attachment, context={"request": request}
            ).data,
            message="Attachment uploaded",
        )


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Delete visit attachment (mobile)",
    responses={200: SIMPLE_SUCCESS, 403: error_schema("Forbidden")},
)
class MobileVisitAttachmentDeleteAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, visit_id, attachment_id):
        visit = get_visit_for_user(request.user, visit_id)
        if visit.employee_id != request.user.id:
            return error_response(message="Not authorized", status_code=403)

        attachment = get_object_or_404(
            VisitAttachment.objects.filter(visit=visit),
            pk=attachment_id,
        )
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
        _invalidate_visit_caches()
        return success_response(message="Attachment deleted")


@extend_schema(
    tags=["Admin", "Visits"],
    summary="List visit attachments (admin)",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("VisitNotFound")},
)
class AdminVisitAttachmentListAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, visit_id):
        visit = get_object_or_404(Visit.objects.all(), pk=visit_id)
        return _serialize_list(request, _attachments_for_visit(visit))
