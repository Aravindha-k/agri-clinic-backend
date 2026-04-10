from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import serializers


class FarmerSerializer(serializers.Serializer):
    farmer_name = serializers.CharField()
    farmer_phone = serializers.CharField()
    village_name = serializers.CharField()
    district_name = serializers.CharField()


from masters.models import (
    Farmer,
    FarmerField,
    FieldCrop,
    CropIssue,
    Recommendation,
    Crop,
    FarmerActivity,
)
from visits.models import Visit, VisitMedia
from visits.serializers import VisitMediaSerializer


# ══════════════════════════════════════════════
# RECOMMENDATION
# ══════════════════════════════════════════════


class RecommendationSerializer(serializers.ModelSerializer):
    given_by_name = serializers.CharField(
        source="given_by.username", read_only=True, default=""
    )

    class Meta:
        model = Recommendation
        fields = [
            "id",
            "issue",
            "given_by",
            "given_by_name",
            "fertilizer",
            "pesticide",
            "dosage",
            "notes",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


class RecommendationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recommendation
        fields = ["fertilizer", "pesticide", "dosage", "notes"]


# ══════════════════════════════════════════════
# CROP ISSUE
# ══════════════════════════════════════════════


class CropIssueSerializer(serializers.ModelSerializer):
    farmer_id = serializers.SerializerMethodField()
    crop_id = serializers.IntegerField(read_only=True)
    visit_id = serializers.IntegerField(read_only=True)
    reported_by = serializers.SerializerMethodField()
    issue_title = serializers.SerializerMethodField()
    visit = serializers.SerializerMethodField()
    farmer = serializers.SerializerMethodField()
    field = serializers.SerializerMethodField()
    crop = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()
    recommendations = RecommendationSerializer(many=True, read_only=True)

    class Meta:
        model = CropIssue
        fields = [
            "id",
            "farmer_id",
            "crop_id",
            "visit_id",
            "reported_by",
            "issue_title",
            "created_at",
            "severity",
            "status",
            "description",
            "visit",
            "farmer",
            "field",
            "crop",
            "employee",
            "recommendations",
        ]
        read_only_fields = ("id", "created_at")

    @extend_schema_field(OpenApiTypes.INT)
    def get_farmer_id(self, obj):
        v = obj.visit
        if not v or not v.farmer_phone:
            return None
        farmer = Farmer.objects.filter(phone=v.farmer_phone).only("id").first()
        return farmer.id if farmer else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_reported_by(self, obj):
        v = obj.visit
        if not v or not v.employee_id:
            return None
        profile = getattr(v.employee, "employee_profile", None)
        if profile and profile.employee_id:
            return profile.employee_id
        return str(v.employee_id)

    @extend_schema_field(OpenApiTypes.STR)
    def get_issue_title(self, obj):
        # Seed data stores title and details as "<title>: <description>".
        text = (obj.description or "").strip()
        if not text:
            return f"Issue #{obj.pk}"
        if ":" in text:
            return text.split(":", 1)[0].strip()
        return text[:60]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_visit(self, obj):
        v = obj.visit
        if not v:
            return None
        return {"id": v.id, "visit_date": str(v.visit_date)}

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_farmer(self, obj):
        v = obj.visit
        if not v:
            return None
        return {
            "name": v.farmer_name or "-",
            "phone": v.farmer_phone or "-",
            "village": v.village.name if v.village else "-",
            "district": v.district.name if v.district else "-",
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_field(self, obj):
        v = obj.visit
        if not v or not v.land_name:
            return None
        return {
            "land_name": v.land_name or "-",
            "land_area": str(v.land_area) if v.land_area else "-",
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_crop(self, obj):
        if not obj.crop_id:
            return None
        return {
            "crop_name": (
                f"{obj.crop.name_en} / {obj.crop.name_ta}" if obj.crop else "-"
            ),
            "season": "-",
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_employee(self, obj):
        v = obj.visit
        if not v or not v.employee_id:
            return None
        emp = v.employee
        profile = getattr(emp, "employee_profile", None)
        return {
            "name": emp.username or "-",
            "employee_id": profile.employee_id if profile else "-",
        }


class CropIssueCreateSerializer(serializers.ModelSerializer):
    recommendations = RecommendationCreateSerializer(many=True, required=False)

    class Meta:
        model = CropIssue
        fields = [
            "crop",
            "severity",
            "description",
            "recommendations",
        ]

    def create(self, validated_data):
        recommendations_data = validated_data.pop("recommendations", [])
        issue = CropIssue.objects.create(**validated_data)
        for rec_data in recommendations_data:
            Recommendation.objects.create(issue=issue, **rec_data)
        return issue


# ══════════════════════════════════════════════
# FIELD CROP
# ══════════════════════════════════════════════


class FieldCropSerializer(serializers.ModelSerializer):
    crop_name = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_crop_name(self, obj):
        if obj.crop:
            return f"{obj.crop.name_en} / {obj.crop.name_ta}"
        return ""

    class Meta:
        model = FieldCrop
        fields = [
            "id",
            "land",
            "crop",
            "crop_name",
            # "season",  # Only include if present in model
            "sowing_date",
            # "expected_harvest_date",  # Only include if present in model
            # "is_active",  # Only include if present in model
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


class FieldCropCreateSerializer(serializers.ModelSerializer):
    # Backward-compatible request fields retained for older clients.
    season = serializers.CharField(required=False, allow_blank=True, write_only=True)
    expected_harvest_date = serializers.DateField(
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = FieldCrop
        fields = [
            "crop",
            "crop_name",
            "season",
            "sowing_date",
            "expected_harvest_date",
            "crop_stage",
        ]

    def create(self, validated_data):
        validated_data.pop("season", None)
        validated_data.pop("expected_harvest_date", None)

        crop = validated_data.get("crop")
        crop_name = (validated_data.get("crop_name") or "").strip()
        if not crop_name and crop:
            crop_name = crop.name_en or crop.name_ta or ""

        if not crop_name:
            raise serializers.ValidationError(
                {"crop_name": "crop_name is required when crop is not provided."}
            )

        validated_data["crop_name"] = crop_name
        return super().create(validated_data)


# ══════════════════════════════════════════════
# FARMER FIELD
# ══════════════════════════════════════════════


class FarmerFieldSerializer(serializers.ModelSerializer):
    crops = FieldCropSerializer(many=True, read_only=True)
    created_by_employee_name = serializers.CharField(
        source="created_by_employee.username", read_only=True, default=""
    )

    class Meta:
        model = FarmerField
        fields = [
            "id",
            "farmer",
            "land_name",
            "land_size",
            "soil_type",
            "irrigation_type",
            "gps_location",
            "crops",
            "created_by_employee",
            "created_by_employee_name",
            "is_active",
            "created_at",
        ]
        read_only_fields = ("id", "created_at", "created_by_employee")


class FarmerFieldCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmerField
        fields = [
            "land_name",
            "land_size",
            "soil_type",
            "irrigation_type",
            "gps_location",
        ]


# ══════════════════════════════════════════════
# VISIT (farmer-centric, lightweight)
# ══════════════════════════════════════════════


class FarmerVisitSerializer(serializers.ModelSerializer):
    """Lightweight visit serializer for embedding inside farmer detail."""

    employee_name = serializers.CharField(
        source="employee.username", read_only=True, default=""
    )
    media_files = VisitMediaSerializer(many=True, read_only=True)
    issues = CropIssueSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id",
            "employee",
            "employee_name",
            "visit_date",
            "latitude",
            "longitude",
            "crop_health",
            "notes",
            "status",
            "visit_time",
            "media_files",
            "issues",
        ]
        read_only_fields = ("id", "visit_time")


# ══════════════════════════════════════════════
# FARMER
# ══════════════════════════════════════════════


class FarmerListSerializer(serializers.ModelSerializer):
    """Lightweight for list views — includes nested fields."""

    village_name = serializers.CharField(
        source="village.name", read_only=True, default=""
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, default=""
    )
    assigned_employee_name = serializers.CharField(
        source="assigned_employee.username", read_only=True, default=""
    )
    fields = FarmerFieldSerializer(many=True, read_only=True)

    class Meta:
        model = Farmer
        fields = [
            "id",
            "farmer_code",
            "name",
            "phone",
            "district",
            "district_name",
            "village",
            "village_name",
            "address",
            "gps_location",
            "total_land_area",
            "irrigation_type",
            "soil_type",
            "assigned_employee",
            "assigned_employee_name",
            "fields",
            "is_active",
            "created_at",
        ]
        read_only_fields = ("id", "farmer_code", "created_at")


class FarmerDetailSerializer(serializers.ModelSerializer):
    """
    Full nested serializer:
    Farmer
    ├── Fields (with Crops)
    └── Recent Visits (with Issues + Media)
    """

    assigned_employee_name = serializers.CharField(
        source="assigned_employee.username", read_only=True, default=""
    )
    fields = FarmerFieldSerializer(many=True, read_only=True)
    recent_visits = serializers.SerializerMethodField()
    activity = serializers.SerializerMethodField()

    class Meta:
        model = Farmer
        fields = [
            "id",
            "farmer_code",
            "name",
            "phone",
            "address",
            "gps_location",
            "total_land_area",
            "irrigation_type",
            "soil_type",
            "assigned_employee",
            "assigned_employee_name",
            "fields",
            "recent_visits",
            "activity",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "farmer_code", "created_at", "updated_at")

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_recent_visits(self, obj):
        from visits.models import Visit as VisitModel

        visits = (
            VisitModel.objects.filter(farmer_phone=obj.phone)
            .select_related("employee")
            .prefetch_related(
                "media_files",
                "issues__crop",
                "issues__recommendations__given_by",
            )
            .order_by("-visit_date")[:10]
        )
        return FarmerVisitSerializer(visits, many=True, context=self.context).data

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_activity(self, obj):
        activities = obj.activities.select_related("created_by").order_by(
            "-created_at"
        )[:20]
        return FarmerActivitySerializer(
            activities, many=True, context=self.context
        ).data


class FarmerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Farmer
        fields = [
            "name",
            "phone",
            "district",
            "village",
            "address",
            "gps_location",
            "total_land_area",
            "irrigation_type",
            "soil_type",
            "assigned_employee",
        ]


class FarmerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Farmer
        fields = [
            "name",
            "phone",
            "district",
            "village",
            "address",
            "gps_location",
            "total_land_area",
            "irrigation_type",
            "soil_type",
            "assigned_employee",
        ]


# ══════════════════════════════════════════════
# FARMER ACTIVITY TIMELINE
# ══════════════════════════════════════════════


class FarmerActivitySerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.username", read_only=True, default=""
    )
    activity_type_display = serializers.CharField(
        source="get_activity_type_display", read_only=True
    )

    class Meta:
        model = FarmerActivity
        fields = [
            "id",
            "farmer",
            "activity_type",
            "activity_type_display",
            "reference_id",
            "created_by",
            "created_by_name",
            "notes",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


# ══════════════════════════════════════════════
# CROP MASTER (expanded)
# ══════════════════════════════════════════════


class CropMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crop
        fields = [
            "id",
            "name_en",
            "name_ta",
            "scientific_name",
            "crop_category",
            "typical_season",
            "is_active",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


class CropMasterCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crop
        fields = [
            "name_en",
            "name_ta",
            "scientific_name",
            "crop_category",
            "typical_season",
        ]

    def validate_name_en(self, value):
        if Crop.objects.filter(name_en__iexact=value).exists():
            raise serializers.ValidationError("A crop with this name already exists.")
        return value
