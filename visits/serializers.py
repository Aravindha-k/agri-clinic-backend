from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import serializers
from masters.models import Crop, Farmer, FarmerField
from visits.access import is_privileged_user
from visits.api_fields import strip_visit_status_from_representation
from visits.submitted import validate_visit_submit_data
from .models import Visit, VisitMedia, VisitAttachment
from .visit_response import build_visit_farmer_block, crop_display_name


class VisitMediaSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VisitMedia
        fields = ["id", "file", "media_type", "caption", "uploaded_at", "file_url"]
        extra_kwargs = {"file": {"write_only": True}}

    @extend_schema_field(OpenApiTypes.URI)
    def get_file_url(self, obj):
        request = self.context.get("request")
        if request and obj.file:
            return request.build_absolute_uri(obj.file.url)
        return None


class VisitMediaUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitMedia
        fields = ["file", "media_type", "caption"]


class VisitSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.username", read_only=True)
    employee_phone = serializers.CharField(
        source="employee.employee_profile.phone", read_only=True, default=""
    )
    village_name = serializers.CharField(source="village.name", read_only=True)
    district_name = serializers.CharField(source="district.name", read_only=True)
    crop_info = serializers.SerializerMethodField()
    crop_name = serializers.SerializerMethodField()
    media_files = VisitMediaSerializer(many=True, read_only=True)
    farmer_info = serializers.SerializerMethodField()
    farmer_name = serializers.SerializerMethodField()
    farmer_mobile = serializers.SerializerMethodField()
    farmer_village = serializers.SerializerMethodField()
    field_info = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        exclude = ("employee", "status")
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {
            "local_sync_id": {"required": False, "allow_null": True, "allow_blank": True},
            "crop": {"required": True, "allow_null": False},
            "latitude": {"required": True, "allow_null": False},
            "longitude": {"required": True, "allow_null": False},
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_crop_info(self, obj):
        if obj.crop:
            return {
                "id": obj.crop.id,
                "name_en": obj.crop.name_en,
                "name_ta": obj.crop.name_ta,
                "name": "{} / {}".format(obj.crop.name_en, obj.crop.name_ta),
            }
        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_crop_name(self, obj):
        return crop_display_name(obj)

    def to_representation(self, instance):
        data = strip_visit_status_from_representation(super().to_representation(instance))
        data["employee"] = instance.employee_id
        block = build_visit_farmer_block(instance)
        if block:
            data["farmer"] = block
        return data

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_farmer_info(self, obj):
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

    def validate(self, data):
        request = self.context.get("request")
        if request is not None and hasattr(request, "data"):
            raw = request.data
            if raw.get("farmer_id") not in (None, "") and not data.get("farmer"):
                data["farmer"] = raw.get("farmer_id")
            if raw.get("crop_id") not in (None, "") and not data.get("crop"):
                data["crop"] = raw.get("crop_id")
            if raw.get("field_id") not in (None, "") and not data.get("field"):
                data["field"] = raw.get("field_id")
        self._link_farmer_and_field(data)
        if self.instance is None:
            validate_visit_submit_data(data)
        return data

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        explicit_employee = validated_data.pop("employee", None)
        is_privileged = getattr(user, "is_staff", False) or getattr(
            user, "is_superuser", False
        )
        if is_privileged and explicit_employee is not None:
            employee = explicit_employee
        else:
            employee = user
        self._link_farmer_and_field(validated_data)
        validated_data.pop("status", None)
        now = timezone.now()
        validated_data.setdefault("visit_date", now.date())
        validated_data.setdefault("visit_time", now.time())
        sync_id = (validated_data.get("local_sync_id") or "").strip() or None
        if sync_id:
            validated_data["local_sync_id"] = sync_id
            existing = Visit.objects.filter(
                employee=employee, local_sync_id=sync_id
            ).first()
            if existing:
                return existing
        else:
            validated_data.pop("local_sync_id", None)
        return Visit.objects.create(**validated_data, employee=employee)

    def update(self, instance, validated_data):
        validated_data.pop("employee", None)
        validated_data.pop("status", None)
        self._link_farmer_and_field(validated_data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        merged = {
            "farmer": instance.farmer,
            "crop": instance.crop,
            "latitude": instance.latitude,
            "longitude": instance.longitude,
        }
        validate_visit_submit_data(merged)
        instance.save()
        return instance

    def _link_farmer_and_field(self, data):
        farmer = data.get("farmer")
        field = data.get("field")

        if field and not farmer:
            farmer = field.farmer
            data["farmer"] = farmer

        if not farmer:
            phone = (data.get("farmer_phone") or "").strip()
            name = (data.get("farmer_name") or "").strip()
            if phone:
                farmer = Farmer.objects.filter(phone=phone).order_by("id").first()
            if farmer is None and name:
                farmer = Farmer.objects.filter(name__iexact=name).order_by("id").first()
            if farmer:
                data["farmer"] = farmer

        if farmer:
            data.setdefault("farmer_name", farmer.name)
            data.setdefault("farmer_phone", farmer.phone)
            data.setdefault("district", farmer.district)
            data.setdefault("village", farmer.village)

        if not field and farmer:
            land_name = (data.get("land_name") or "").strip()
            if land_name:
                field = (
                    FarmerField.objects.filter(
                        farmer=farmer, land_name__iexact=land_name
                    )
                    .order_by("id")
                    .first()
                )
            if field:
                data["field"] = field

        if field:
            data.setdefault("land_name", field.land_name)
            if data.get("land_area") is None and field.land_size is not None:
                data["land_area"] = float(field.land_size)
