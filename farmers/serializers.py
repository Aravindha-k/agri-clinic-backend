from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from django.db.models import Q
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
from utils.serializer_mixins import ProfilePhotoUrlMixin


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
        if not v:
            return None
        if v.farmer_id:
            return v.farmer_id
        if not v.farmer_phone:
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
        if v.farmer_id:
            return {
                "id": v.farmer_id,
                "name": v.farmer.name or "-",
                "phone": v.farmer.phone or "-",
                "village": v.farmer.village.name if v.farmer.village else "-",
                "district": v.farmer.district.name if v.farmer.district else "-",
            }
        return {
            "name": v.farmer_name or "-",
            "phone": v.farmer_phone or "-",
            "village": v.village.name if v.village else "-",
            "district": v.district.name if v.district else "-",
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_field(self, obj):
        v = obj.visit
        if not v:
            return None
        if v.field_id:
            return {
                "id": v.field_id,
                "land_name": v.field.land_name or "-",
                "land_area": str(v.field.land_size) if v.field.land_size else "-",
            }
        if not v.land_name:
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
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=""
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, default=""
    )
    crop_info = serializers.SerializerMethodField()
    field_info = serializers.SerializerMethodField()
    media_files = VisitMediaSerializer(many=True, read_only=True)
    issues = CropIssueSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id",
            "farmer",
            "field",
            "farmer_name",
            "farmer_phone",
            "land_name",
            "land_area",
            "employee",
            "employee_name",
            "visit_date",
            "latitude",
            "longitude",
            "village_name",
            "district_name",
            "crop",
            "crop_info",
            "field_info",
            "crop_health",
            "notes",
            "status",
            "visit_time",
            "media_files",
            "issues",
        ]
        read_only_fields = ("id", "visit_time")

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_crop_info(self, obj):
        if obj.crop:
            return {
                "id": obj.crop.id,
                "name_en": obj.crop.name_en,
                "name_ta": obj.crop.name_ta,
                "name": f"{obj.crop.name_en} / {obj.crop.name_ta}",
            }
        return None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_field_info(self, obj):
        if obj.field_id:
            return {
                "id": obj.field_id,
                "land_name": obj.field.land_name,
                "land_size": str(obj.field.land_size) if obj.field.land_size else None,
            }
        if obj.land_name or obj.land_area is not None:
            return {"id": None, "land_name": obj.land_name, "land_area": obj.land_area}
        return None


# ══════════════════════════════════════════════
# FARMER
# ══════════════════════════════════════════════


class FarmerListSerializer(ProfilePhotoUrlMixin, serializers.ModelSerializer):
    """Admin list — core fields + visit stats (no nested fields payload)."""

    mobile = serializers.CharField(source="phone", read_only=True)
    village = serializers.CharField(source="village.name", read_only=True, default="")
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=""
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, default=""
    )
    crop_name = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    visit_count = serializers.IntegerField(read_only=True, default=0)
    visits = serializers.IntegerField(source="visit_count", read_only=True, default=0)
    total_visits = serializers.IntegerField(source="visit_count", read_only=True, default=0)
    latest_visit_date = serializers.DateField(read_only=True, allow_null=True)
    total_land_area = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, allow_null=True
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_crop_name(self, obj):
        annotated = getattr(obj, "list_crop_name", None)
        if annotated:
            return annotated
        return ""

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_latitude(self, obj):
        from .helpers import parse_gps_location

        lat, _ = parse_gps_location(getattr(obj, "gps_location", None))
        return lat

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_longitude(self, obj):
        from .helpers import parse_gps_location

        _, lng = parse_gps_location(getattr(obj, "gps_location", None))
        return lng

    class Meta:
        model = Farmer
        fields = [
            "id",
            "name",
            "phone",
            "mobile",
            "village",
            "village_name",
            "district_name",
            "crop_name",
            "latitude",
            "longitude",
            "total_land_area",
            "visit_count",
            "visits",
            "total_visits",
            "latest_visit_date",
            "profile_photo_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class FarmerDetailSerializer(ProfilePhotoUrlMixin, serializers.ModelSerializer):
    """
    Full nested serializer:
    Farmer
    ├── Fields (with Crops)
    └── Recent Visits (with Issues + Media)
    """

    district_name = serializers.CharField(
        source="district.name", read_only=True, default=""
    )
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=""
    )
    assigned_employee_name = serializers.CharField(
        source="assigned_employee.username", read_only=True, default=""
    )
    # Named farmer_fields — "fields" shadows ModelSerializer.get_fields().
    farmer_fields = serializers.SerializerMethodField()
    recent_visits = serializers.SerializerMethodField()
    activity = serializers.SerializerMethodField()

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
            "profile_photo_url",
            "farmer_fields",
            "recent_visits",
            "activity",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "farmer_code", "created_at", "updated_at")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if "farmer_fields" in data:
            data["fields"] = data.pop("farmer_fields")
        return data

    @extend_schema_field(serializers.ListSerializer(child=FarmerFieldSerializer()))
    def get_farmer_fields(self, obj):
        qs = obj.fields.filter(is_active=True).prefetch_related("crops__crop")
        return FarmerFieldSerializer(qs, many=True, context=self.context).data

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_recent_visits(self, obj):
        from visits.models import Visit as VisitModel

        visits = (
            VisitModel.objects.filter(Q(farmer=obj) | Q(farmer_phone=obj.phone))
            .select_related("employee", "farmer", "field")
            .prefetch_related(
                "media_files",
                "issues__crop",
                "issues__recommendations__given_by",
            )
            .order_by("-created_at", "-id")
        )
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
            visits = visits.filter(employee=user)
        visits = visits[:10]
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

    def validate_phone(self, value):
        phone = (value or "").strip()
        if not phone:
            raise serializers.ValidationError("Phone is required.")
        qs = Farmer.objects.filter(phone=phone)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A farmer with this mobile number already exists."
            )
        return phone


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
