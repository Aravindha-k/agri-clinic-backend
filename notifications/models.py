from django.db import models
from django.conf import settings


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ("GPS_OFF", "GPS Off"),
        ("OFFLINE", "Offline"),
        ("ONLINE", "Online"),
        ("VISIT_CREATED", "Visit Created"),
        ("VISIT_BLOCKED", "Visit Blocked"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPES,
    )

    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.notification_type} - {self.created_at}"
