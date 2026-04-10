import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.pagination import StandardPagination
from utils.response import success_response
from utils.schema import PAGINATION_PARAMS, paginated_response_schema

from .models import AuditLog
from .serializers import AuditLogSerializer

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Audit Logs"],
    summary="List audit logs (admin)",
    description=(
        "Full audit trail of system actions. Admin only.  \n\n"
        "**Filterable by:** `module`, `action`, `actor`, `entity_id`, `date_from`, `date_to`"
    ),
    parameters=[
        *PAGINATION_PARAMS,
        OpenApiParameter(
            "module",
            OpenApiTypes.STR,
            description="Filter by module name (e.g. `ACCOUNTS`, `VISITS`, `FARMERS`).",
        ),
        OpenApiParameter(
            "action",
            OpenApiTypes.STR,
            description="Filter by action type: `CREATE`, `UPDATE`, `DELETE`, `LOGIN`, `LOGOUT`, `STATUS_CHANGE`, `UPLOAD`.",
        ),
        OpenApiParameter(
            "actor",
            OpenApiTypes.STR,
            description="Filter by actor username (substring match).",
        ),
        OpenApiParameter(
            "entity_id",
            OpenApiTypes.STR,
            description="Filter by exact entity / object ID.",
        ),
        OpenApiParameter(
            "date_from",
            OpenApiTypes.DATE,
            description="Start date filter (inclusive). Format: `YYYY-MM-DD`.",
        ),
        OpenApiParameter(
            "date_to",
            OpenApiTypes.DATE,
            description="End date filter (inclusive). Format: `YYYY-MM-DD`.",
        ),
    ],
    responses={200: AuditLogSerializer(many=True)},
)
class AuditLogListAPI(APIView):
    """
    GET /api/v1/audit/
    Query params:
      - module       (e.g. ACCOUNTS, VISITS)
      - action       (e.g. CREATE, UPDATE, DELETE, LOGIN)
      - actor        (username substring)
      - entity_id    (object_id exact match)
      - date_from    (ISO date, inclusive)
      - date_to      (ISO date, inclusive)
      - page, page_size
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = AuditLog.objects.select_related("actor").order_by("-created_at")

        module = request.query_params.get("module", "").strip().upper()
        if module:
            qs = qs.filter(module=module)

        action = request.query_params.get("action", "").strip().upper()
        if action:
            qs = qs.filter(action=action)

        actor = request.query_params.get("actor", "").strip()
        if actor:
            qs = qs.filter(actor__username__icontains=actor)

        entity_id = request.query_params.get("entity_id", "").strip()
        if entity_id:
            qs = qs.filter(object_id=entity_id)

        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AuditLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
