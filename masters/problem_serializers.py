from rest_framework import serializers

from masters.models import ProblemCategory, ProblemMaster, Crop, Village
from masters.problem_item_utils import api_category_code


class ProblemCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProblemCategory
        fields = [
            "id",
            "code",
            "name",
            "description",
            "requires_problem_master",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")


class ProblemCategoryDropdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProblemCategory
        fields = ["id", "code", "name", "requires_problem_master"]


class ProblemMasterSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    crop_name = serializers.SerializerMethodField()

    class Meta:
        model = ProblemMaster
        fields = [
            "id",
            "category",
            "category_code",
            "category_name",
            "name",
            "tamil_name",
            "crop",
            "crop_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at", "category_code", "category_name")

    def get_crop_name(self, obj):
        if not obj.crop_id:
            return None
        return f"{obj.crop.name_en} / {obj.crop.name_ta}"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.category_id:
            data["category_id"] = instance.category_id
            data["category_code"] = instance.category.code
            data["category"] = api_category_code(instance.category.code)
        return data

    def validate(self, attrs):
        category = attrs.get("category") or getattr(self.instance, "category", None)
        crop = attrs.get("crop", getattr(self.instance, "crop", None))
        if category and crop and crop.id and not crop.is_active:
            raise serializers.ValidationError({"crop": "Crop must be active."})
        return attrs


class ProblemMasterDropdownSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", read_only=True)

    class Meta:
        model = ProblemMaster
        fields = [
            "id",
            "name",
            "tamil_name",
            "category_id",
            "category_code",
            "crop_id",
        ]


class VisitFormOptionsSerializer(serializers.Serializer):
    villages = serializers.ListField()
    crops = serializers.ListField()
    problem_categories = serializers.ListField()
    problem_masters = serializers.ListField()
