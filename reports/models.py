from django.conf import settings
from django.db import models


class Report(models.Model):
    """
    Tracks every generated report: who requested it, what type,
    current status, and where the file is stored.
    """

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    REPORT_TYPE_CHOICES = [
        ("visit_summary", "Visit Summary"),
        ("employee_performance", "Employee Performance"),
        ("village_summary", "Village Summary"),
        ("farmer_history", "Farmer History"),
        ("daily_summary", "Daily Summary"),
        ("monthly_summary", "Monthly Summary"),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE_CHOICES)
    parameters = models.JSONField(
        default=dict, blank=True, help_text="Filter params used"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    file = models.FileField(upload_to="reports/", null=True, blank=True)
    file_url = models.URLField(max_length=1000, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["requested_by", "status"]),
            models.Index(fields=["report_type"]),
        ]

    def __str__(self):
        return f"{self.report_type} | {self.status} | {self.created_at:%Y-%m-%d %H:%M}"
