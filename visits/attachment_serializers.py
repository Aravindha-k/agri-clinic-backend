from drf_spectacular.openapi import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from visits.attachments import (
    ATTACHMENT_TYPE_TEXT,
    guess_mime_type,
    normalize_attachment_type,
    validate_attachment_payload,
)
from visits.models import VisitAttachment


class VisitAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username", read_only=True, default=""
    )
    employee_username = serializers.CharField(
        source="employee.username", read_only=True, default=""
    )

    class Meta:
        model = VisitAttachment
        fields = [
            "id",
            "visit",
            "employee",
            "attachment_type",
            "file",
            "file_url",
            "text_content",
            "original_filename",
            "mime_type",
            "file_size",
            "uploaded_at",
            "uploaded_by",
            "uploaded_by_username",
            "employee_username",
        ]
        read_only_fields = [
            "id",
            "visit",
            "employee",
            "file_url",
            "original_filename",
            "mime_type",
            "file_size",
            "uploaded_at",
            "uploaded_by",
            "uploaded_by_username",
            "employee_username",
        ]
        extra_kwargs = {"file": {"write_only": True}}

    @extend_schema_field(OpenApiTypes.URI)
    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.pop("file", None)
        return data


class VisitAttachmentCreateSerializer(serializers.Serializer):
    attachment_type = serializers.CharField()
    file = serializers.FileField(required=False, allow_null=True)
    text_content = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def validate(self, attrs):
        attachment_type = normalize_attachment_type(attrs.get("attachment_type"))
        errors = validate_attachment_payload(
            attachment_type=attachment_type,
            file_obj=attrs.get("file"),
            text_content=attrs.get("text_content"),
        )
        if errors:
            raise serializers.ValidationError(errors)
        attrs["attachment_type"] = attachment_type
        return attrs

    def create(self, validated_data):
        visit = self.context["visit"]
        user = self.context["request"].user
        attachment_type = validated_data["attachment_type"]
        file_obj = validated_data.get("file")
        text_content = (validated_data.get("text_content") or "").strip()

        payload = {
            "visit": visit,
            "employee": visit.employee,
            "attachment_type": attachment_type,
            "uploaded_by": user,
            "text_content": text_content or None,
        }

        if attachment_type == ATTACHMENT_TYPE_TEXT:
            return VisitAttachment.objects.create(**payload)

        original_filename = getattr(file_obj, "name", "") or ""
        payload.update(
            {
                "file": file_obj,
                "original_filename": original_filename,
                "mime_type": guess_mime_type(
                    original_filename, getattr(file_obj, "content_type", "")
                ),
                "file_size": getattr(file_obj, "size", 0) or 0,
            }
        )
        return VisitAttachment.objects.create(**payload)
