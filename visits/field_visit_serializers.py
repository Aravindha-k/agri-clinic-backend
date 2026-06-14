"""Write serializer for client Field Visit (Add Visit) form."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers

from masters.models import Crop, Farmer, ProblemCategory, ProblemMaster, Village
from visits.farmer_inline import get_or_create_farmer_for_field_visit
from visits.field_notes import apply_observation_write
from visits.field_visit import merge_field_visit_request_aliases, validate_visit_submit_data
from visits.models import Visit
from utils.gps import validate_latitude_longitude


class FieldVisitSubmitSerializer(serializers.ModelSerializer):
    """
    Canonical Add Visit payload (admin + mobile).
    Legacy GPS-only submits remain supported when full GPS + farmer + crop sent.
    """

    age = serializers.IntegerField(required=False, write_only=True)
    phone = serializers.CharField(required=False, write_only=True)
    phone_number = serializers.CharField(required=False, write_only=True)
    acreage = serializers.FloatField(required=False, write_only=True)
    create_farmer_if_missing = serializers.BooleanField(
        required=False, default=True, write_only=True
    )
    problem_category_id = serializers.PrimaryKeyRelatedField(
        queryset=ProblemCategory.objects.filter(is_active=True),
        source="problem_category",
        required=False,
        write_only=True,
    )
    problem_master_id = serializers.PrimaryKeyRelatedField(
        queryset=ProblemMaster.objects.filter(is_active=True).select_related("category"),
        source="problem_master",
        required=False,
        allow_null=True,
        write_only=True,
    )
    village_id = serializers.PrimaryKeyRelatedField(
        queryset=Village.objects.filter(is_active=True),
        source="village",
        required=False,
        write_only=True,
    )
    crop_id = serializers.PrimaryKeyRelatedField(
        queryset=Crop.objects.filter(is_active=True),
        source="crop",
        required=False,
        write_only=True,
    )
    farmer_id = serializers.PrimaryKeyRelatedField(
        queryset=Farmer.objects.filter(is_active=True),
        source="farmer",
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = Visit
        fields = [
            "farmer_id",
            "farmer_name",
            "age",
            "phone",
            "phone_number",
            "farmer_phone",
            "farmer_age",
            "village_id",
            "village",
            "crop_id",
            "crop",
            "acreage",
            "land_area",
            "problem_category_id",
            "problem_category",
            "problem_master_id",
            "problem_master",
            "problem_description",
            "problem_seen",
            "recommendation",
            "observation",
            "action_taken",
            "follow_up_required",
            "next_visit_date",
            "latitude",
            "longitude",
            "local_sync_id",
            "field",
            "land_name",
            "create_farmer_if_missing",
        ]
        extra_kwargs = {
            "farmer_name": {"required": False},
            "farmer_phone": {"required": False},
            "farmer_age": {"required": False},
            "village": {"required": False},
            "crop": {"required": False},
            "land_area": {"required": False},
            "problem_category": {"required": False},
            "problem_master": {"required": False},
            "problem_description": {"required": False},
            "recommendation": {"required": False, "allow_null": True, "allow_blank": True},
            "observation": {"required": False, "allow_null": True, "allow_blank": True},
            "action_taken": {"required": False, "allow_null": True, "allow_blank": True},
            "follow_up_required": {"required": False, "allow_null": True},
            "next_visit_date": {"required": False, "allow_null": True},
            "latitude": {"required": False, "allow_null": True},
            "longitude": {"required": False, "allow_null": True},
            "local_sync_id": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def _apply_request_aliases(self, data, raw):
        merge_field_visit_request_aliases(data, raw)
        if raw.get("farmer_id") not in (None, "") and not data.get("farmer"):
            data["farmer"] = raw.get("farmer_id")
        if raw.get("age") not in (None, "") and data.get("farmer_age") is None:
            data["farmer_age"] = raw.get("age")

    def validate(self, data):
        request = self.context.get("request")
        raw = request.data if request is not None and hasattr(request, "data") else {}
        self._apply_request_aliases(data, raw)
        create_flag = raw.get("create_farmer_if_missing", True)
        if isinstance(create_flag, str):
            create_flag = create_flag.strip().lower() not in {"false", "0", "no"}
        self._link_farmer_and_field(data, create_if_missing=bool(create_flag))
        apply_observation_write(data, raw, instance=self.instance)

        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is not None and lng is not None:
            validate_latitude_longitude(lat, lng)

        if self.instance is None:
            validate_visit_submit_data(data, raw)
        return data

    def create(self, validated_data):
        validated_data.pop("age", None)
        validated_data.pop("phone", None)
        validated_data.pop("phone_number", None)
        validated_data.pop("acreage", None)
        validated_data.pop("create_farmer_if_missing", None)
        validated_data.pop("problem_subcategory", None)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        validated_data.pop("status", None)

        employee = user
        if user and user.is_staff and request is not None:
            emp_id = request.data.get("employee_id") or request.data.get("employee")
            if emp_id not in (None, ""):
                try:
                    employee = User.objects.get(pk=emp_id, is_active=True)
                except User.DoesNotExist:
                    raise serializers.ValidationError(
                        {"employee_id": "Invalid employee."}
                    )
        validated_data.pop("employee", None)

        now = timezone.now()
        validated_data.setdefault("visit_date", now.date())
        validated_data.setdefault("visit_time", now.time())
        sync_id = (validated_data.get("local_sync_id") or "").strip() or None
        if sync_id:
            validated_data["local_sync_id"] = sync_id
            existing = Visit.objects.filter(employee=employee, local_sync_id=sync_id).first()
            if existing:
                return existing
        else:
            validated_data.pop("local_sync_id", None)
        return Visit.objects.create(**validated_data, employee=employee)

    def update(self, instance, validated_data):
        validated_data.pop("age", None)
        validated_data.pop("phone", None)
        validated_data.pop("phone_number", None)
        validated_data.pop("acreage", None)
        validated_data.pop("create_farmer_if_missing", None)
        validated_data.pop("problem_subcategory", None)
        validated_data.pop("status", None)
        self._link_farmer_and_field(validated_data, create_if_missing=False)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        validate_visit_submit_data(
            {
                "farmer": instance.farmer,
                "farmer_name": instance.farmer_name,
                "farmer_phone": instance.farmer_phone,
                "farmer_age": instance.farmer_age,
                "village": instance.village,
                "crop": instance.crop,
                "land_area": instance.land_area,
                "problem_category": instance.problem_category,
                "problem_master": instance.problem_master,
                "problem_description": instance.problem_description,
                "latitude": instance.latitude,
                "longitude": instance.longitude,
            }
        )
        instance.save()
        return instance

    def _resolve_farmer(self, farmer):
        if farmer is None or isinstance(farmer, Farmer):
            return farmer
        try:
            return Farmer.objects.get(pk=farmer)
        except (Farmer.DoesNotExist, TypeError, ValueError):
            return None

    def _link_farmer_and_field(self, data, *, create_if_missing: bool):
        farmer = self._resolve_farmer(data.get("farmer"))
        village = data.get("village")
        if isinstance(village, int):
            try:
                village = Village.objects.get(pk=village)
                data["village"] = village
            except Village.DoesNotExist:
                village = None

        if farmer:
            data["farmer"] = farmer
            data.setdefault("farmer_name", farmer.name)
            data.setdefault("farmer_phone", farmer.phone)
            data.setdefault("district", farmer.district)
            if not data.get("village") and farmer.village_id:
                data["village"] = farmer.village

        field = data.get("field")
        if field and not farmer:
            data["farmer"] = field.farmer
            farmer = field.farmer

        if not farmer:
            phone = (data.get("farmer_phone") or data.get("phone_number") or "").strip()
            name = (data.get("farmer_name") or "").strip()
            if phone:
                farmer = Farmer.objects.filter(phone=phone).order_by("id").first()
            if farmer is None and name:
                farmer = Farmer.objects.filter(name__iexact=name).order_by("id").first()

        if not farmer and create_if_missing and village:
            phone = data.get("farmer_phone") or data.get("phone_number")
            name = (data.get("farmer_name") or "").strip()
            if phone and name:
                request = self.context.get("request")
                user = getattr(request, "user", None)
                farmer, _created = get_or_create_farmer_for_field_visit(
                    name=name,
                    phone=phone,
                    village=village,
                    created_by=user,
                )

        if farmer:
            data["farmer"] = farmer
            data["farmer_name"] = farmer.name
            data["farmer_phone"] = farmer.phone
            data.setdefault("district", farmer.district)
            if not data.get("village") and farmer.village_id:
                data["village"] = farmer.village
