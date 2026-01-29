from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification


class NotificationListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_staff:
            notifications = Notification.objects.all().order_by("-created_at")
        else:
            notifications = Notification.objects.filter(user=request.user).order_by(
                "-created_at"
            )

        data = []
        for n in notifications:
            data.append(
                {
                    "id": n.id,
                    "type": n.notification_type,
                    "message": n.message,
                    "created_at": n.created_at,
                    "is_read": n.is_read,
                }
            )

        return Response(data)
