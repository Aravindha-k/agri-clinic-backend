from .models import Notification


def create_notification(user, notification_type, message):
    Notification.objects.create(
        user=user,
        notification_type=notification_type,
        message=message,
    )
