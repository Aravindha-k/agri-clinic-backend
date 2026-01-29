from django.conf import settings
from django.db import models


# ✅ MAIN VISIT TABLE
class Visit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    farmer_name = models.CharField(max_length=100)
    farmer_phone = models.CharField(max_length=15)

    village = models.CharField(max_length=100)
    crop_type = models.CharField(max_length=100)
    problem_category = models.CharField(max_length=100)

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    visit_time = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.farmer_name} - {self.visit_time}"


# ✅ ATTACHMENTS (IMAGE / BILL / PDF / VOICE)
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

    # ✅ REAL FILE UPLOAD STORAGE
    file = models.FileField(upload_to="visit_attachments/")

    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_type} File for Visit {self.visit.id}"
