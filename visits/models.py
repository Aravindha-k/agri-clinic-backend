from django.conf import settings
from django.db import models
from masters.models import Village, Crop
from django.contrib.auth.models import User


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
    farmer_name = models.CharField(max_length=255, null=True, blank=True)
    farmer_phone = models.CharField(max_length=20, blank=True, null=True, db_index=True)

    # Land Details (manual)
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
        max_length=20, choices=STATUS_CHOICES, default="pending", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    FILE_TYPES = (
        ("CROP", "Crop Photo"),
        ("SOIL", "Soil Photo"),
        ("BILL", "Bill"),
        ("VOICE", "Voice Note"),
        ("PDF", "PDF Report"),
        ("OTHER", "Other"),
    )

    visit = models.ForeignKey(
        Visit,
        related_name="attachments",
        on_delete=models.CASCADE,
    )

    file_type = models.CharField(max_length=20, choices=FILE_TYPES)

    file = models.FileField(upload_to="visit_attachments/")

    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_type} | Visit {self.visit_id}"
