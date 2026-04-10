from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    ACTION_CHOICES = (
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("LOGIN", "Login"),
        ("LOGOUT", "Logout"),
        ("STATUS_CHANGE", "Status Change"),
        ("UPLOAD", "Upload"),
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    module = models.CharField(max_length=50)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)

    object_id = models.CharField(max_length=100, null=True, blank=True)

    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.module} | {self.action} | {self.created_at}"
