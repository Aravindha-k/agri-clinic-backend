import uuid
from django.db import models


# ==========================================================
# BASE MASTER MODEL
# ==========================================================


class BaseMaster(models.Model):
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    class Meta:
        abstract = True


# ==========================================================
# LOCATION MASTERS
# ==========================================================


class District(BaseMaster):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Village(BaseMaster):

    name = models.CharField(max_length=255)
    district = models.ForeignKey(
        "District",
        on_delete=models.PROTECT,
        related_name="villages",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["name"]
        indexes = []

    def __str__(self):
        return self.name


# ==========================================================
# AGRICULTURE MASTERS
# ==========================================================


class Crop(BaseMaster):
    CROP_CATEGORY_CHOICES = [
        ("cereal", "Cereal"),
        ("pulse", "Pulse"),
        ("oilseed", "Oilseed"),
        ("vegetable", "Vegetable"),
        ("fruit", "Fruit"),
        ("spice", "Spice"),
        ("fiber", "Fiber"),
        ("commercial", "Commercial"),
        ("other", "Other"),
    ]
    SEASON_CHOICES = [
        ("kharif", "Kharif"),
        ("rabi", "Rabi"),
        ("zaid", "Zaid / Summer"),
        ("annual", "Annual"),
    ]

    name_en = models.CharField(max_length=255)
    name_ta = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    scientific_name = models.CharField(max_length=255, blank=True, default="")
    crop_category = models.CharField(
        max_length=20,
        choices=CROP_CATEGORY_CHOICES,
        blank=True,
        default="",
    )
    typical_season = models.CharField(
        max_length=20,
        choices=SEASON_CHOICES,
        blank=True,
        default="",
    )

    class Meta:
        ordering = ["name_en"]

    def __str__(self):
        return f"{self.name_en} / {self.name_ta}"


class ProblemCategory(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ==========================================================
# FARMER MASTER
# ==========================================================


class Farmer(BaseMaster):
    IRRIGATION_CHOICES = [
        ("rainfed", "Rainfed"),
        ("borewell", "Borewell"),
        ("canal", "Canal"),
        ("drip", "Drip"),
        ("sprinkler", "Sprinkler"),
        ("other", "Other"),
    ]
    SOIL_CHOICES = [
        ("red", "Red Soil"),
        ("black", "Black Soil"),
        ("alluvial", "Alluvial"),
        ("laterite", "Laterite"),
        ("sandy", "Sandy"),
        ("clay", "Clay"),
        ("loamy", "Loamy"),
        ("other", "Other"),
    ]

    farmer_code = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15)
    district = models.ForeignKey(
        District,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farmers",
    )

    village = models.ForeignKey(
        Village,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farmers",
    )
    address = models.TextField(blank=True, default="")
    gps_location = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Lat,Lng e.g. 12.345678,79.123456",
    )
    total_land_area = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total land area in acres",
    )
    irrigation_type = models.CharField(
        max_length=20,
        choices=IRRIGATION_CHOICES,
        blank=True,
        default="",
    )
    soil_type = models.CharField(
        max_length=20,
        choices=SOIL_CHOICES,
        blank=True,
        default="",
    )
    profile_photo = models.ImageField(
        upload_to="farmer_photos/%Y/%m/",
        null=True,
        blank=True,
    )
    assigned_employee = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_farmers",
    )
    created_by_employee = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_farmers",
        help_text="Employee who created the farmer record",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["farmer_code"]),
            models.Index(fields=["assigned_employee"]),
        ]

    def save(self, *args, **kwargs):
        if not self.farmer_code:
            self.farmer_code = self._generate_code()
        super().save(*args, **kwargs)

    def _generate_code(self):
        import uuid as _uuid

        prefix = "FRM"
        short = _uuid.uuid4().hex[:8].upper()
        return f"{prefix}-{short}"

    def __str__(self):
        return f"{self.farmer_code} | {self.name} | {self.phone}"


# ==========================================================
# FARMER FIELD
# ==========================================================


class FarmerField(BaseMaster):
    IRRIGATION_CHOICES = Farmer.IRRIGATION_CHOICES
    SOIL_CHOICES = Farmer.SOIL_CHOICES

    farmer = models.ForeignKey(
        Farmer,
        on_delete=models.CASCADE,
        related_name="fields",
    )
    land_name = models.CharField(max_length=255)
    land_size = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Land size in acres",
    )
    soil_type = models.CharField(
        max_length=20,
        choices=SOIL_CHOICES,
        blank=True,
        default="",
    )
    irrigation_type = models.CharField(
        max_length=20,
        choices=IRRIGATION_CHOICES,
        blank=True,
        default="",
    )
    gps_location = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Lat,Lng or GeoJSON polygon",
    )
    created_by_employee = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_fields",
        help_text="Employee who created the land record",
    )

    class Meta:
        ordering = ["land_name"]

    def __str__(self):
        return f"{self.farmer.name} - {self.land_name}"


# ==========================================================
# FIELD CROP
# ==========================================================


class FieldCrop(BaseMaster):
    SEASON_CHOICES = [
        ("kharif", "Kharif"),
        ("rabi", "Rabi"),
        ("zaid", "Zaid / Summer"),
        ("annual", "Annual"),
    ]

    land = models.ForeignKey(
        FarmerField,
        on_delete=models.CASCADE,
        related_name="crops",
    )
    crop_name = models.CharField(max_length=255)
    sowing_date = models.DateField(null=True, blank=True)
    crop_stage = models.CharField(max_length=100, blank=True, default="")

    # Optionally keep reference to Crop master
    crop = models.ForeignKey(
        Crop,
        on_delete=models.PROTECT,
        related_name="field_crops",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-sowing_date"]

    def __str__(self):
        return f"{self.land} - {self.crop_name}"


# ==========================================================
# CROP ISSUE
# ==========================================================


class CropIssue(models.Model):
    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("under_review", "Under Review"),
        ("resolved", "Resolved"),
    ]

    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.CASCADE,
        related_name="issues",
    )
    crop = models.ForeignKey(
        Crop,
        on_delete=models.PROTECT,
        related_name="issues",
        null=True,
        blank=True,
    )
    severity = models.CharField(
        max_length=10,
        choices=SEVERITY_CHOICES,
        default="medium",
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="open",
        db_index=True,
    )
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Issue #{self.pk} | Visit {self.visit_id}"


# ==========================================================
# RECOMMENDATION
# ==========================================================


class Recommendation(models.Model):
    issue = models.ForeignKey(
        CropIssue,
        on_delete=models.CASCADE,
        related_name="recommendations",
    )
    given_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="given_recommendations",
    )
    fertilizer = models.CharField(max_length=255, blank=True, default="")
    pesticide = models.CharField(max_length=255, blank=True, default="")
    dosage = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rec #{self.pk} for Issue #{self.issue_id}"


# ==========================================================
# FARMER ACTIVITY TIMELINE
# ==========================================================


class FarmerActivity(models.Model):
    ACTIVITY_TYPE_CHOICES = [
        ("FARMER_CREATED", "Farmer Created"),
        ("VISIT_COMPLETED", "Visit Completed"),
        ("ISSUE_REPORTED", "Issue Reported"),
        ("RECOMMENDATION_GIVEN", "Recommendation Given"),
        ("FOLLOWUP_VISIT", "Follow-up Visit"),
    ]

    farmer = models.ForeignKey(
        Farmer,
        on_delete=models.CASCADE,
        related_name="activities",
        null=True,
        blank=True,
    )
    activity_type = models.CharField(
        max_length=30,
        choices=ACTIVITY_TYPE_CHOICES,
    )
    reference_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="ID of the related object (Visit, CropIssue, etc.)",
    )
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farmer_activities",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["farmer"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["farmer", "activity_type"]),
        ]
        verbose_name_plural = "Farmer activities"

    def __str__(self):
        return f"{self.farmer.name} | {self.activity_type} | {self.created_at}"
