from drf_spectacular.openapi import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from utils.photo_urls import build_profile_photo_url


class ProfilePhotoUrlMixin(serializers.Serializer):
    profile_photo_url = serializers.SerializerMethodField()
    profile_photo_updated_at = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.URI)
    def get_profile_photo_url(self, obj):
        request = self.context.get("request")
        photo = getattr(obj, "profile_photo", None)
        return build_profile_photo_url(request, photo)

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_profile_photo_updated_at(self, obj):
        updated = getattr(obj, "profile_photo_updated_at", None)
        return updated.isoformat() if updated else None
