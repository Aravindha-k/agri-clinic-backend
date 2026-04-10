from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import serializers
from masters.models import Crop, Village
from .models import Visit, VisitMedia, VisitAttachment


class StartVisitSerializer(serializers.Serializer):
    crop = serializers.PrimaryKeyRelatedField(
        queryset=Crop.objects.filter(is_active=True)
    )
    latitude = serializers.DecimalField(max_digits=10, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=6)
    farmer_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    village = serializers.PrimaryKeyRelatedField(
        queryset=Village.objects.all(), required=False, allow_null=True, default=None
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


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
    media_files = VisitMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        exclude = ("employee",)

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

    def validate(self, data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        is_admin = getattr(user, "is_staff", False)
        errors = {}
        if not is_admin:
            if data.get("latitude") is None:
                errors["latitude"] = "This field is required for employees."
            if data.get("longitude") is None:
                errors["longitude"] = "This field is required for employees."
        if errors:
            raise serializers.ValidationError(errors)
        return data

    def create(self, validated_data):
        request = self.context.get("request")
        return Visit.objects.create(**validated_data, employee=request.user)
