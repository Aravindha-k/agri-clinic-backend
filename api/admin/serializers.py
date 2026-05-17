from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import serializers

from masters.models import (
    Farmer,
    FarmerField,
    FieldCrop,
    Crop,
    CropIssue,
    Recommendation,
)
from visits.models import Visit, VisitMedia
from visits.api_fields import strip_visit_status_from_representation
from visits.visit_response import build_visit_farmer_block, crop_display_name


# ──────────────────────────────────────────────
# Crop
# ──────────────────────────────────────────────


class AdminCropSerializer(serializers.ModelSerializer):
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


# ──────────────────────────────────────────────
# Recommendation (nested inside Issue)
# ──────────────────────────────────────────────


class AdminRecommendationSerializer(serializers.ModelSerializer):
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


# ──────────────────────────────────────────────
# CropIssue
# ──────────────────────────────────────────────


class AdminCropIssueSerializer(serializers.ModelSerializer):
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
    recommendations = AdminRecommendationSerializer(many=True, read_only=True)

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
        annotated_id = getattr(obj, "admin_farmer_id", None)
        if annotated_id:
            return annotated_id
        annotated_id = getattr(obj, "admin_farmer_id_by_phone", None)
        if annotated_id:
            return annotated_id
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
        crop = obj.crop
        return {
            "crop_name": f"{crop.name_en} / {crop.name_ta}" if crop else "-",
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


# ──────────────────────────────────────────────
# FieldCrop (nested inside FarmerField)
# ──────────────────────────────────────────────


class AdminFieldCropSerializer(serializers.ModelSerializer):
    crop_name = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_crop_name(self, obj):
        if obj.crop:
            return f"{obj.crop.name_en} / {obj.crop.name_ta}"
        return ""

    field_name = serializers.CharField(
        source="land.land_name", read_only=True, default=""
    )
    farmer_name = serializers.CharField(
        source="land.farmer.name", read_only=True, default=""
    )

    class Meta:
        model = FieldCrop
        fields = [
            "id",
            "land",
            "field_name",
            "farmer_name",
            "crop",
            "crop_name",
            "sowing_date",
            "crop_stage",
            "is_active",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


# ──────────────────────────────────────────────
# FarmerField
# ──────────────────────────────────────────────


class AdminFarmerFieldSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(
        source="farmer.name", read_only=True, default=""
    )
    farmer_code = serializers.CharField(
        source="farmer.farmer_code", read_only=True, default=""
    )
    created_by_employee_name = serializers.CharField(
        source="created_by_employee.username", read_only=True, default=""
    )
    crops = AdminFieldCropSerializer(many=True, read_only=True)

    class Meta:
        model = FarmerField
        fields = [
            "id",
            "farmer",
            "farmer_name",
            "farmer_code",
            "land_name",
            "land_size",
            "soil_type",
            "irrigation_type",
            "gps_location",
            "created_by_employee",
            "created_by_employee_name",
            "crops",
            "is_active",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


# ──────────────────────────────────────────────
# Visit
# ──────────────────────────────────────────────


class AdminVisitMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitMedia
        fields = ["id", "file", "media_type", "uploaded_at"]
        read_only_fields = ("id", "uploaded_at")


class AdminVisitSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.username", read_only=True, default=""
    )
    land_size = serializers.SerializerMethodField()
    location_label = serializers.SerializerMethodField()
    farmer = serializers.SerializerMethodField()
    farmer_display = serializers.SerializerMethodField()
    farmer_name = serializers.SerializerMethodField()
    farmer_mobile = serializers.SerializerMethodField()
    farmer_village = serializers.SerializerMethodField()
    field_display = serializers.SerializerMethodField()
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=""
    )
    crop_name = serializers.SerializerMethodField()
    issues = AdminCropIssueSerializer(many=True, read_only=True)
    media_files = AdminVisitMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        exclude = ("status",)
        read_only_fields = ("id", "visit_time")

    def to_representation(self, instance):
        return strip_visit_status_from_representation(super().to_representation(instance))

    @extend_schema_field(OpenApiTypes.STR)
    def get_crop_name(self, obj):
        return crop_display_name(obj)

    @extend_schema_field(OpenApiTypes.STR)
    def get_land_size(self, obj):
        if obj.field_id and obj.field.land_size is not None:
            return str(obj.field.land_size)
        if obj.land_area is not None:
            return str(obj.land_area)
        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_location_label(self, obj):
        if obj.village_id:
            return obj.village.name
        if obj.farmer_id and obj.farmer.village_id:
            return obj.farmer.village.name
        return ""

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_farmer(self, obj):
        return build_visit_farmer_block(obj)

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_farmer_display(self, obj):
        block = build_visit_farmer_block(obj)
        if not block:
            return None
        out = {
            "id": block.get("id"),
            "name": block.get("name"),
            "phone": block.get("mobile") or block.get("phone"),
        }
        if obj.farmer_id and obj.farmer.farmer_code:
            out["farmer_code"] = obj.farmer.farmer_code
        return out

    @extend_schema_field(OpenApiTypes.STR)
    def get_farmer_name(self, obj):
        block = build_visit_farmer_block(obj)
        return block.get("name") if block else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_farmer_mobile(self, obj):
        block = build_visit_farmer_block(obj)
        return block.get("mobile") if block else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_farmer_village(self, obj):
        block = build_visit_farmer_block(obj)
        return block.get("village") if block else None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_field_display(self, obj):
        if obj.field_id:
            return {
                "id": obj.field_id,
                "land_name": obj.field.land_name,
                "land_size": str(obj.field.land_size) if obj.field.land_size else None,
            }
        return {"id": None, "land_name": obj.land_name, "land_area": obj.land_area}


# ──────────────────────────────────────────────
# Farmer
# ──────────────────────────────────────────────


class AdminFarmerSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(
        source="district.name", read_only=True, default=""
    )
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=""
    )
    assigned_employee_name = serializers.CharField(
        source="assigned_employee.username", read_only=True, default=""
    )
    fields = AdminFarmerFieldSerializer(many=True, read_only=True)

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
            "updated_at",
        ]
        read_only_fields = ("id", "farmer_code", "created_at", "updated_at")
