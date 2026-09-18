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
    district_name = serializers.CharField(source="district.name", read_only=True)
    taluk_name = serializers.CharField(source="taluk.name", read_only=True)

    class Meta:
        model = Village
        fields = [
            "id",
            "name",
            "official_code",
            "district",
            "district_name",
            "taluk",
            "taluk_name",
            "is_active",
        ]
        read_only_fields = ("created_at", "updated_at")
        extra_kwargs = {
            "district": {"required": False},
            "taluk": {"required": False},
        }

    def validate(self, attrs):
        taluk = attrs.get("taluk")
        if taluk is None and self.instance is not None:
            taluk = self.instance.taluk
        if self.instance is None and taluk is None:
            raise serializers.ValidationError(
                {"taluk": "Taluk is required for a new village."}
            )
        if taluk is not None:
            if not taluk.district_id:
                raise serializers.ValidationError(
                    {"taluk": "Taluk must belong to a district."}
                )
            attrs["taluk"] = taluk
            attrs["district"] = taluk.district
        return attrs


class VillageLightweightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Village
        fields = ["id", "name", "official_code"]


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
    Derive Farmer.district / Farmer.taluk from Village.

    Client-supplied district/taluk are ignored when a village is present.
    Villages without an active Taluk/District cannot be newly assigned.
    """
    village = attrs.get("village", getattr(instance, "village", None) if instance else None)
    if village is not None and not isinstance(village, Village):
        village = (
            Village.objects.filter(pk=getattr(village, "pk", village))
            .select_related("taluk", "taluk__district")
            .first()
        )
        attrs["village"] = village
    elif isinstance(village, Village) and village.taluk_id and getattr(village, "taluk", None) is None:
        village = (
            Village.objects.filter(pk=village.pk)
            .select_related("taluk", "taluk__district")
            .first()
        )
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
    if not village.taluk_id:
        raise serializers.ValidationError(
            {"village": "Village does not belong to a taluk."}
        )
    taluk = village.taluk
    if taluk is None:
        taluk = (
            Taluk.objects.select_related("district").filter(pk=village.taluk_id).first()
        )
    if not taluk or not taluk.is_active:
        raise serializers.ValidationError(
            {"village": "Village does not belong to an active taluk."}
        )
    district = taluk.district
    if not district or not district.is_active:
        raise serializers.ValidationError(
            {"village": "Village does not belong to an active district."}
        )
    attrs["village"] = village
    attrs["taluk"] = taluk
    attrs["district"] = district
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
    """Validate district/taluk/village consistency. Inactive values cannot be newly assigned.

    require_complete: new farmers, or an edit that changes location fields, must
    supply a full District -> Taluk -> Village hierarchy. Do not silently infer
    Taluk from village name. Unrelated PATCH of an existing legacy farmer
    (taluk NULL) must still succeed.
    """
    district = attrs.get("district", getattr(instance, "district", None) if instance else None)
    taluk = attrs.get("taluk", getattr(instance, "taluk", None) if instance else None)
    village = attrs.get("village", getattr(instance, "village", None) if instance else None)

    # Resolve PKs that arrived as ints.
    if isinstance(district, int):
        district = District.objects.filter(pk=district).first()
        attrs["district"] = district
    if isinstance(taluk, int):
        taluk = Taluk.objects.filter(pk=taluk).first()
        attrs["taluk"] = taluk
    if isinstance(village, int):
        village = Village.objects.filter(pk=village).first()
        attrs["village"] = village

    errors = {}
    assigning_district = "district" in attrs and attrs["district"] is not None
    assigning_taluk = "taluk" in attrs and attrs["taluk"] is not None
    assigning_village = "village" in attrs and attrs["village"] is not None

    if assigning_district and district and not district.is_active:
        errors["district"] = "Inactive district cannot be newly assigned."
    if assigning_taluk and taluk and not taluk.is_active:
        errors["taluk"] = "Inactive taluk cannot be newly assigned."
    if assigning_village and village and not village.is_active:
        errors["village"] = "Inactive village cannot be newly assigned."

    if require_complete:
        if not district:
            errors["district"] = "District is required."
        if not taluk:
            errors["taluk"] = "Taluk is required."
        if not village:
            errors["village"] = "Village is required."
        elif not village.taluk_id:
            errors["village"] = "Village does not belong to a taluk."

    if taluk and district and taluk.district_id != district.id:
        errors["taluk"] = "Taluk does not belong to the selected district."
    if village and taluk and village.taluk_id and village.taluk_id != taluk.id:
        errors["village"] = "Village does not belong to the selected taluk."
    if village and district and village.district_id and village.district_id != district.id:
        errors["village"] = "Village does not belong to the selected district."

    if errors:
        raise serializers.ValidationError(errors)
    return attrs


class FarmerSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(
        source="village.name", read_only=True, default=None
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
