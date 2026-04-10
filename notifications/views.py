from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, serializers

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.response import success_response, error_response
from utils.pagination import SmallPagination
from utils.schema import (
    paginated_response_schema,
    SIMPLE_SUCCESS,
    error_schema,
    PAGINATION_PARAMS,
)
from .models import Notification
from . import services as notification_services

_NOTIFICATION_ITEM = {
    "id": serializers.IntegerField(),
    "type": serializers.CharField(),
    "message": serializers.CharField(),
    "created_at": serializers.DateTimeField(),
    "is_read": serializers.BooleanField(),
}


@extend_schema(
    tags=["Notifications"],
    summary="List notifications",
    description=(
        "Returns paginated notifications for the authenticated user.  \n"
        "Admin users see all notifications; regular users see only their own.  \n"
        "Use `?unread=true` to return only unread notifications."
    ),
    parameters=[
        *PAGINATION_PARAMS,
        OpenApiParameter(
            "unread",
            OpenApiTypes.BOOL,
            description="Pass `true` to return only unread notifications.",
        ),
    ],
    responses={200: paginated_response_schema("NotificationList", _NOTIFICATION_ITEM)},
)
class NotificationListAPI(APIView):
    """GET /api/v1/notifications/  or  /api/v1/notifications/list/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_staff:
            qs = Notification.objects.all().order_by("-created_at")
        else:
            qs = Notification.objects.filter(user=request.user).order_by("-created_at")

        # Optional filter: unread only
        unread_only = request.query_params.get("unread")
        if unread_only and unread_only.lower() == "true":
            qs = qs.filter(is_read=False)

        paginator = SmallPagination()
        page = paginator.paginate_queryset(qs, request)

        data = [
            {
                "id": n.id,
                "type": n.notification_type,
                "message": n.message,
                "created_at": n.created_at,
                "is_read": n.is_read,
            }
            for n in page
        ]

        return paginator.get_paginated_response(data)


@extend_schema(
    tags=["Notifications"],
    summary="Mark notification as read",
    description="Marks a single notification as read. Returns 404 if not found or already read.",
    request=None,
    responses={200: SIMPLE_SUCCESS, 404: error_schema("NotificationNotFound")},
)
class NotificationMarkReadAPI(APIView):
    """POST /api/v1/notifications/{id}/read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        updated = notification_services.mark_as_read(
            notification_id=pk, user=request.user
        )
        if not updated:
            return error_response(
                message="Notification not found or already read.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return success_response(message="Marked as read.")


@extend_schema(
    tags=["Notifications"],
    summary="Mark all notifications as read",
    description="Marks all of the current user's unread notifications as read.",
    request=None,
    responses={200: SIMPLE_SUCCESS},
)
class NotificationMarkAllReadAPI(APIView):
    """POST /api/v1/notifications/mark-all-read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = notification_services.mark_all_as_read(user=request.user)
        return success_response(
            data={"updated": count},
            message=f"{count} notification(s) marked as read.",
        )


@extend_schema(
    tags=["Notifications"],
    summary="Unread notification count",
    description="Returns the count of unread notifications for the authenticated user.",
    responses={
        200: {
            "description": "Unread count",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "OK",
                        "data": {"unread_count": 5},
                    }
                }
            },
        }
    },
)
class NotificationUnreadCountAPI(APIView):
    """GET /api/v1/notifications/unread-count/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = notification_services.get_unread_count(request.user)
        return success_response(data={"unread_count": count})

        return success_response(data={"unread_count": count})
