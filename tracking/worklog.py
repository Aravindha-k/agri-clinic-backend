from django.db import models
from django.conf import settings


class WorkLog(models.Model):
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="work_logs",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    total_duration = models.DurationField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_time"]
        indexes = [
            models.Index(fields=["employee", "is_active"]),
        ]

    def __str__(self):
        return f"{self.employee.username} | {self.start_time}"
