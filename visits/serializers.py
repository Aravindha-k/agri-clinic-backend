from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import serializers
from visits.api_fields import strip_visit_status_from_representation
from utils.gps import validate_latitude_longitude
from .models import Visit, VisitMedia, VisitAttachment
from .field_notes import apply_observation_write, observation_response_block
from .visit_response import (
    build_field_visit_problem_block,
    build_field_visit_snapshot,
    build_visit_employee_block,
    build_visit_farmer_block,
    crop_display_name,
)


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

    def validate(self, attrs):
        from visits.media_validation import validate_visit_media_file

        errors = validate_visit_media_file(
            file_obj=attrs.get("file"),
            media_type=attrs.get("media_type", ""),
        )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


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
    employee_profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        exclude = ("employee", "status")
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {
            "local_sync_id": {"required": False, "allow_null": True, "allow_blank": True},
            "crop": {"required": False, "allow_null": True},
            "latitude": {"required": False, "allow_null": True},
            "longitude": {"required": False, "allow_null": True},
            "follow_up_required": {"required": False, "allow_null": True},
            "next_visit_date": {"required": False, "allow_null": True},
            "recommendation": {"required": False, "allow_null": True},
            "observation": {"required": False, "allow_null": True},
            "action_taken": {"required": False, "allow_null": True},
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

    @extend_schema_field(OpenApiTypes.URI)
    def get_employee_profile_photo_url(self, obj):
        block = build_visit_employee_block(obj, self.context.get("request"))
        return block.get("profile_photo_url")

    def to_representation(self, instance):
        request = self.context.get("request")
        data = strip_visit_status_from_representation(super().to_representation(instance))
        data["employee"] = instance.employee_id
        data["employee_detail"] = build_visit_employee_block(instance, request)
        block = build_visit_farmer_block(instance, request)
        if block:
            data["farmer"] = block
        data.update(observation_response_block(instance))
        if data.get("crop_info"):
            data["crop"] = data["crop_info"]
        data["field_visit_snapshot"] = build_field_visit_snapshot(instance)
        problem = build_field_visit_problem_block(instance)
        if problem:
            data["field_visit"] = problem
            data.update(problem)
            if problem.get("problem_master"):
                data["problem_item"] = problem["problem_master"]
        media = data.get("media_files") or []
        data["evidence"] = {
            "media": media,
            "media_count": len(media),
        }
        return data

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_farmer_info(self, obj):
        block = build_visit_farmer_block(obj, self.context.get("request"))
        if not block:
            return None
        out = {
            "id": block.get("id"),
            "name": block.get("name"),
            "phone": block.get("mobile") or block.get("phone"),
            "profile_photo_url": block.get("profile_photo_url"),
        }
        if obj.farmer_id and obj.farmer.farmer_code:
            out["farmer_code"] = obj.farmer.farmer_code
        return out

    @extend_schema_field(OpenApiTypes.STR)
    def get_farmer_name(self, obj):
        block = build_visit_farmer_block(obj, self.context.get("request"))
        return block.get("name") if block else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_farmer_mobile(self, obj):
        block = build_visit_farmer_block(obj, self.context.get("request"))
        return block.get("mobile") if block else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_farmer_village(self, obj):
        block = build_visit_farmer_block(obj, self.context.get("request"))
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
        raw = request.data if request is not None and hasattr(request, "data") else {}
        apply_observation_write(data, raw, instance=self.instance)
        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is not None and lng is not None:
            validate_latitude_longitude(lat, lng)
        return data
