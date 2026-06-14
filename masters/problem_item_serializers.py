from rest_framework import serializers

from masters.models import Crop, ProblemMaster
from masters.problem_item_utils import (
    ALLOWED_API_CATEGORIES,
    api_category_code,
    get_category_for_api_code,
)


class ProblemItemSerializer(serializers.ModelSerializer):
    """API-facing Problem Item (backed by ProblemMaster)."""

    category = serializers.CharField()
    crop = serializers.PrimaryKeyRelatedField(
        queryset=Crop.objects.all(),
        allow_null=True,
        required=False,
    )
    crop_name = serializers.SerializerMethodField()

    class Meta:
        model = ProblemMaster
        fields = [
            "id",
            "name",
            "tamil_name",
            "category",
            "crop",
            "crop_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at", "crop_name")

    def get_crop_name(self, obj):
        if not obj.crop_id:
            return None
        return obj.crop.name_en

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["category"] = api_category_code(instance.category.code)
        return data

    def validate_category(self, value):
        code = (value or "").strip().lower()
        if code not in ALLOWED_API_CATEGORIES:
            raise serializers.ValidationError(
                "Category must be one of: pest, disease, nutrient_issue."
            )
        return code

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Name is required.")
        return name

    def validate(self, attrs):
        api_category = attrs.pop("category", None)
        if api_category is None and self.instance is not None:
            api_category = api_category_code(self.instance.category.code)
        if api_category is None:
            raise serializers.ValidationError({"category": "Category is required."})
        try:
            attrs["category"] = get_category_for_api_code(api_category)
        except ValueError as exc:
            raise serializers.ValidationError({"category": str(exc)}) from exc

        crop = attrs.get("crop", getattr(self.instance, "crop", None))
        if crop and not crop.is_active:
            raise serializers.ValidationError({"crop": "Crop must be active."})
        return attrs
