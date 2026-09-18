from rest_framework import serializers
from .models import (
    District,
    Taluk,
    Village,
    Crop,
    ProblemCategory,
    Farmer,
    FarmerField,
    FieldCrop,
)


class DistrictSerializer(serializers.ModelSerializer):
    taluk_count = serializers.IntegerField(read_only=True, required=False, default=0)
    village_count = serializers.IntegerField(read_only=True, required=False, default=0)

    class Meta:
        model = District
        fields = ["id", "name", "is_active", "taluk_count", "village_count"]
        read_only_fields = ("created_at", "updated_at", "taluk_count", "village_count")

    def validate_name(self, value):
        qs = District.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("District already exists.")
        return value


class TalukSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source="district.name", read_only=True)
    village_count = serializers.IntegerField(read_only=True, required=False, default=0)

    class Meta:
        model = Taluk
        fields = [
            "id",
            "name",
            "district",
            "district_name",
            "is_active",
            "village_count",
        ]
        read_only_fields = ("created_at", "updated_at", "district_name", "village_count")


class VillageSerializer(serializers.ModelSerializer):
    tamil_name = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, default="", allow_null=True
    )
    taluk_name = serializers.CharField(
        source="taluk.name", read_only=True, default="", allow_null=True
    )

    class Meta:
        model = Village
        fields = [
            "id",
            "name",
            "name_ta",
            "tamil_name",
            "official_code",
            "district",
            "district_name",
            "taluk",
            "taluk_name",
            "is_active",
        ]
        read_only_fields = ("created_at", "updated_at")
        extra_kwargs = {
            "district": {"required": False, "allow_null": True},
            "taluk": {"required": False, "allow_null": True},
            "name_ta": {"required": False, "allow_blank": True},
        }

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)
        if not (data.get("name_ta") or "").strip() and data.get("tamil_name"):
            data["name_ta"] = data.get("tamil_name")
        return super().to_internal_value(data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["tamil_name"] = instance.name_ta or ""
        return data

    def validate_name(self, value):
        from masters.location_utils import find_village_by_normalized_name

        value = " ".join((value or "").strip().split())
        if not value:
            raise serializers.ValidationError("Village name is required.")
        existing = find_village_by_normalized_name(value)
        if existing and (self.instance is None or existing.pk != self.instance.pk):
            raise serializers.ValidationError("A village with this name already exists.")
        return value

    def validate(self, attrs):
        attrs.pop("tamil_name", None)
        # Operational create/update does not require district/taluk/firka.
        # If a legacy taluk is supplied, keep Village.district consistent.
        taluk = attrs.get("taluk")
        if taluk is not None and getattr(taluk, "district_id", None):
            attrs["district"] = taluk.district
        return attrs


class VillageLightweightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Village
        fields = ["id", "name", "name_ta", "is_active", "official_code"]


class CropSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crop
        fields = ["id", "name_en", "name_ta"]


from masters.problem_serializers import (  # noqa: F401
    ProblemCategorySerializer,
    ProblemMasterSerializer,
)


def _location_pk(value):
    if value is None:
        return None
    return getattr(value, "pk", value)


def location_fields_changed(attrs, instance) -> bool:
    """True on create, or when district/taluk/village actually changes."""
    if instance is None:
        return True
    for key in ("district", "taluk", "village"):
        if key not in attrs:
            continue
        if _location_pk(attrs[key]) != _location_pk(getattr(instance, key, None)):
            return True
    return False


def bind_farmer_location_from_village(
    attrs, instance=None, *, require_village=False
):
    """
    Bind Farmer.village. District/taluk are not operational and are left
    null on new village assignment.
    """
    village = attrs.get("village", getattr(instance, "village", None) if instance else None)
    if village is not None and not isinstance(village, Village):
        village = Village.objects.filter(pk=getattr(village, "pk", village)).first()
        attrs["village"] = village

    if require_village and not village:
        raise serializers.ValidationError({"village": "Village is required."})
    if village is None:
        return attrs

    assigning_village = "village" in attrs and attrs["village"] is not None
    if assigning_village and not village.is_active:
        raise serializers.ValidationError(
            {"village": "Inactive village cannot be newly assigned."}
        )
    attrs["village"] = village
    if assigning_village:
        attrs["taluk"] = None
        attrs["district"] = None
    return attrs


def _enforce_employee_farmer_village(attrs, request, instance=None):
    from accounts.territory import (
        assert_village_in_employee_territory,
        user_requires_territory_scope,
    )

    user = getattr(request, "user", None) if request is not None else None
    if not user_requires_territory_scope(user):
        return attrs
    village = attrs.get("village")
    if village is None and instance is not None:
        village = instance.village
    assert_village_in_employee_territory(user, village)
    return attrs


def validate_farmer_location_hierarchy(attrs, instance=None, *, require_complete=False):
    """Village-only location validation. District/taluk are not operational.

    require_complete: new farmers, or an edit that changes location fields, must
    supply Village. Unrelated PATCH of an existing farmer must still succeed.
    """
    village = attrs.get("village", getattr(instance, "village", None) if instance else None)

    if isinstance(village, int):
        village = Village.objects.filter(pk=village).first()
        attrs["village"] = village

    errors = {}
    assigning_village = "village" in attrs and attrs["village"] is not None

    if assigning_village and village and not village.is_active:
        errors["village"] = "Inactive village cannot be newly assigned."

    if require_complete and not village:
        errors["village"] = "Village is required."

    if errors:
        raise serializers.ValidationError(errors)
    return attrs


class FarmerSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=None
    )
    village_name_ta = serializers.CharField(
        source="village.name_ta", read_only=True, default=""
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, default=None
    )
    taluk_name = serializers.CharField(
        source="taluk.name", read_only=True, default=None
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

    def validate(self, attrs):
        request = self.context.get("request")
        from accounts.territory import user_requires_territory_scope

        user = getattr(request, "user", None) if request else None
        employee_scoped = user_requires_territory_scope(user)
        if location_fields_changed(attrs, self.instance) or attrs.get("village") is not None:
            attrs = bind_farmer_location_from_village(
                attrs,
                instance=self.instance,
                require_village=employee_scoped,
            )
        return _enforce_employee_farmer_village(
            attrs, request, instance=self.instance
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
