from rest_framework import serializers
from .models import (
    District,
    Village,
    Crop,
    ProblemCategory,
    Farmer,
    FarmerField,
    FieldCrop,
)


class DistrictSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")

    def validate_name(self, value):
        if District.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError("District already exists.")
        return value


class VillageSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source="district.name", read_only=True)

    class Meta:
        model = Village
        fields = ["id", "name", "district", "district_name"]
        read_only_fields = ("created_at", "updated_at")


class CropSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crop
        fields = ["id", "name_en", "name_ta"]


from masters.problem_serializers import (  # noqa: F401
    ProblemCategorySerializer,
    ProblemMasterSerializer,
)


class FarmerSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=None
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, default=None
    )

    created_by_employee_username = serializers.CharField(
        source="created_by_employee.username", read_only=True, default=None
    )
    assigned_employee_name = serializers.CharField(
        source="assigned_employee.username", read_only=True, default=None
    )

    class Meta:
        model = Farmer
        fields = "__all__"
        read_only_fields = (
            "created_at",
            "updated_at",
            "created_by_employee",
            "farmer_code",
        )


# =========================
# LAND SERIALIZER
# =========================
class FarmerFieldSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.name", read_only=True)
    created_by_employee_username = serializers.CharField(
        source="created_by_employee.username", read_only=True, default=None
    )

    class Meta:
        model = FarmerField
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at", "created_by_employee")
        ref_name = "MastersFarmerField"


# =========================
# CROP SERIALIZER
# =========================
class FieldCropSerializer(serializers.ModelSerializer):
    land_name = serializers.CharField(source="land.land_name", read_only=True)
    crop_name = serializers.CharField(read_only=True)

    class Meta:
        model = FieldCrop
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")
        ref_name = "MastersFieldCrop"
