from django.conf import settings
from django.db import models
from masters.models import Village, Crop
from django.contrib.auth.models import User

from visits.attachments import ATTACHMENT_TYPE_CHOICES


# New Visit model as per requirements
class Visit(models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("completed", "Completed"),
        ("pending", "Pending"),
    ]

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="visits",
        db_index=True,
    )
    visit_date = models.DateField(db_index=True, null=True, blank=True)
    visit_time = models.TimeField(null=True, blank=True)

    # Location
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    district = models.ForeignKey(
        "masters.District", on_delete=models.PROTECT, null=True, blank=True
    )
    village = models.ForeignKey(
        "masters.Village", on_delete=models.PROTECT, null=True, blank=True
    )

    # Farmer Details (manual)
    farmer = models.ForeignKey(
        "masters.Farmer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
        db_index=True,
    )
    farmer_name = models.CharField(max_length=255, null=True, blank=True)
    farmer_phone = models.CharField(max_length=20, blank=True, null=True, db_index=True)

    # Land Details (manual)
    field = models.ForeignKey(
        "masters.FarmerField",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
        db_index=True,
    )
    land_name = models.CharField(max_length=255, null=True, blank=True)
    land_area = models.FloatField(null=True, blank=True)

    # Crop Details
    crop = models.ForeignKey(
        "masters.Crop",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )
    crop_stage = models.CharField(max_length=100, blank=True, null=True)
    variety = models.CharField(max_length=100, null=True, blank=True)
    season = models.CharField(max_length=100, null=True, blank=True)
    sowing_date = models.DateField(null=True, blank=True)

    # Observations
    crop_health = models.CharField(max_length=100, null=True, blank=True)
    pest_issue = models.BooleanField(default=False, null=True, blank=True)
    disease_issue = models.BooleanField(default=False, null=True, blank=True)
    weed_condition = models.CharField(max_length=100, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    # Recommendations
    fertilizer_advice = models.TextField(blank=True, null=True)
    pesticide_advice = models.TextField(blank=True, null=True)
    irrigation_advice = models.TextField(blank=True, null=True)
    general_advice = models.TextField(blank=True, null=True)

    # Follow-up
    follow_up_required = models.BooleanField(default=False, null=True, blank=True)
    next_visit_date = models.DateField(null=True, blank=True)

    # System
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="completed", null=True, blank=True
    )
    local_sync_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="Client-generated id for offline sync deduplication.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["employee", "created_at"]),
            models.Index(fields=["employee", "visit_date"]),
            models.Index(fields=["farmer", "visit_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "local_sync_id"],
                condition=models.Q(local_sync_id__isnull=False)
                & ~models.Q(local_sync_id=""),
                name="uniq_visit_employee_local_sync_id",
            )
        ]

    def __str__(self):
        return f"Visit {self.id} - {self.farmer_name} - {self.visit_date}"


class VisitMedia(models.Model):

    MEDIA_TYPE_CHOICES = [
        ("image", "Image"),
        ("bill", "Bill"),
        ("audio", "Audio"),
        ("video", "Video"),
    ]
    visit = models.ForeignKey(
        Visit, on_delete=models.CASCADE, related_name="media_files"
    )
    file = models.FileField(upload_to="visit_media/")
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPE_CHOICES)
    caption = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.media_type} | Visit {self.visit_id}"


class VisitAttachment(models.Model):
    """Evidence attached to a visit (photo, PDF, audio, text note, etc.)."""

    visit = models.ForeignKey(
        Visit,
        related_name="attachments",
        on_delete=models.CASCADE,
        db_index=True,
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="visit_attachments",
        db_index=True,
    )
    attachment_type = models.CharField(
        max_length=20,
        choices=ATTACHMENT_TYPE_CHOICES,
        db_index=True,
    )
    file = models.FileField(
        upload_to="visit_attachments/%Y/%m/",
        null=True,
        blank=True,
    )
    text_content = models.TextField(blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    mime_type = models.CharField(max_length=128, blank=True, default="")
    file_size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_visit_attachments",
    )

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"{self.attachment_type} | Visit {self.visit_id}"

    @property
    def file_type(self):
        """Backward-compatible alias used by legacy upload endpoints."""
        legacy = {
            "image": "CROP",
            "pdf": "PDF",
            "audio": "VOICE",
            "text": "OTHER",
            "other": "OTHER",
        }
        return legacy.get(self.attachment_type, "OTHER")
