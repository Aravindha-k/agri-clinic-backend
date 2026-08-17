"""Write serializer for client Field Visit (Add Visit) form.

Validation stays here; persistence is owned by
``visits.services.field_visit_service``.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from rest_framework import serializers

from masters.models import Crop, Farmer, ProblemCategory, ProblemMaster, Village
from visits.field_notes import apply_observation_write
from visits.field_visit import merge_field_visit_request_aliases, validate_visit_submit_data
from visits.models import Visit
from visits.problem_selection import (
    apply_problem_items_to_visit,
    resolve_problem_items_for_visit,
)
from visits.services.farmer_resolution import resolve_farmer_for_visit
from visits.services.field_visit_service import (
    ensure_visit_route_point,
    submit_field_visit_validated,
)
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
    problem_item_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
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
            "problem_item_ids",
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
        employee = getattr(request, "user", None) if request else None
        resolve_farmer_for_visit(
            data, employee=employee, create_if_missing=bool(create_flag)
        )
        apply_observation_write(data, raw, instance=self.instance)

        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is not None and lng is not None:
            validate_latitude_longitude(lat, lng)

        # Multi-problem resolution before required-field validation so
        # problem_item_ids can satisfy problem_master / category requirements.
        raw_ids = None
        has_new_ids = False
        if hasattr(raw, "get") and "problem_item_ids" in raw:
            has_new_ids = True
            raw_ids = raw.get("problem_item_ids")
        if "problem_item_ids" in data:
            has_new_ids = True
            raw_ids = data.pop("problem_item_ids")
        crop = data.get("crop")
        crop_id = getattr(crop, "pk", data.get("crop_id") or crop)
        problems = resolve_problem_items_for_visit(
            problem_item_ids=raw_ids if has_new_ids else None,
            legacy_master=data.get("problem_master"),
            crop_id=crop_id,
        )
        if problems:
            data["problem_master"] = problems[0]
            data["problem_category"] = problems[0].category
        data["_resolved_problem_items"] = problems

        if self.instance is None:
            validate_visit_submit_data(data, raw)
        return data

    def create(self, validated_data):
        problems = validated_data.pop("_resolved_problem_items", None)
        request = self.context.get("request")
        user = getattr(request, "user", None)
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
        if employee is None:
            raise serializers.ValidationError(
                {"employee": "Authenticated employee required."}
            )

        result = submit_field_visit_validated(
            employee=employee,
            validated_data=validated_data,
            request=request,
        )
        visit = result.visit
        if problems is not None:
            apply_problem_items_to_visit(visit, problems)
        # Stash for transport adapters that need duplicate flag without re-query.
        visit._field_visit_submit_result = result  # type: ignore[attr-defined]
        return visit

    def update(self, instance, validated_data):
        problems = validated_data.pop("_resolved_problem_items", None)
        for key in (
            "age",
            "phone",
            "phone_number",
            "acreage",
            "create_farmer_if_missing",
            "problem_subcategory",
            "status",
            "local_sync_id",
            "duty_session",
            "employee",
        ):
            validated_data.pop(key, None)

        request = self.context.get("request")
        employee = getattr(request, "user", None) if request else instance.employee
        resolve_farmer_for_visit(
            validated_data, employee=employee, create_if_missing=False
        )
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
        if problems is not None:
            apply_problem_items_to_visit(instance, problems)
        ensure_visit_route_point(instance)
        return instance
