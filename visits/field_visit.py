"""
Field visit submit rules (client Add Visit form).

Supports legacy GPS submit and new canonical field-visit payload.
"""

from __future__ import annotations

from typing import Any, Optional

from django.db.models import Q, QuerySet
from rest_framework import serializers

from masters.models import ProblemCategory, ProblemMaster, Village
from visits.models import Visit

FIELD_VISIT_REQUIRED_MESSAGE = (
    "Farmer name, phone, village, crop, acreage, problem category, "
    "and problem description are required."
)

LEGACY_SUBMIT_REQUIRED_MESSAGE = (
    "Farmer, crop, and GPS location are required to submit a visit."
)

SUBMIT_VISIT_REQUIRED_MESSAGE = FIELD_VISIT_REQUIRED_MESSAGE


def _positive_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _normalize_phone(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def _resolve_pk(data: dict, object_key: str, *id_keys: str) -> Any:
    obj = data.get(object_key)
    if obj not in (None, ""):
        return getattr(obj, "pk", obj)
    for key in id_keys:
        val = data.get(key)
        if val not in (None, ""):
            return val
    return None


def _resolve_phone(data: dict, farmer: Any = None) -> str:
    phone = _normalize_phone(
        data.get("farmer_phone")
        or data.get("phone_number")
        or data.get("phone")
        or data.get("mobile")
    )
    if not phone and farmer is not None:
        phone = _normalize_phone(getattr(farmer, "phone", ""))
    return phone


def _resolve_problem_description(data: dict) -> str:
    return (
        data.get("problem_description")
        or data.get("problem_seen")
        or data.get("notes")
        or ""
    ).strip()


def merge_field_visit_request_aliases(data: dict, raw: dict | None) -> None:
    """Map admin/mobile request keys into canonical validate/create keys."""
    raw = raw if isinstance(raw, dict) else {}
    id_map = (
        ("farmer_id", "farmer"),
        ("crop_id", "crop"),
        ("village_id", "village"),
        ("problem_category_id", "problem_category"),
        ("problem_master_id", "problem_master"),
        ("problem_subcategory_id", "problem_master"),
    )
    for raw_key, target in id_map:
        if raw.get(raw_key) not in (None, "") and not data.get(target):
            data[target] = raw.get(raw_key)

    phone_val = (
        raw.get("phone_number")
        or raw.get("phone")
        or raw.get("mobile")
        or raw.get("farmer_phone")
    )
    if phone_val not in (None, "") and not data.get("farmer_phone"):
        data["farmer_phone"] = phone_val

    if raw.get("acreage") not in (None, "") and data.get("land_area") is None:
        data["land_area"] = raw.get("acreage")
    if raw.get("land_size") not in (None, "") and data.get("land_area") is None:
        data["land_area"] = raw.get("land_size")

    for desc_key in ("problem_description", "problem_seen", "notes"):
        if raw.get(desc_key) not in (None, "") and not _resolve_problem_description(data):
            data["problem_description"] = raw.get(desc_key)

    pid = raw.get("problem_id")
    if pid not in (None, ""):
        if not _resolve_pk(data, "problem_category", "problem_category_id"):
            try:
                data["problem_category"] = ProblemCategory.objects.get(
                    pk=pid, is_active=True
                )
            except ProblemCategory.DoesNotExist:
                try:
                    master = ProblemMaster.objects.select_related("category").get(
                        pk=pid, is_active=True
                    )
                    data["problem_master"] = master
                    data["problem_category"] = master.category
                except ProblemMaster.DoesNotExist:
                    data.setdefault("problem_category_id", pid)
        if not data.get("problem_master") and not _resolve_pk(
            data, "problem_master", "problem_master_id", "problem_subcategory_id"
        ):
            try:
                master = ProblemMaster.objects.select_related("category").get(
                    pk=pid, is_active=True
                )
                data["problem_master"] = master
                if not _resolve_pk(data, "problem_category", "problem_category_id"):
                    data["problem_category"] = master.category
            except ProblemMaster.DoesNotExist:
                pass


def category_requires_master(category: ProblemCategory | None) -> bool:
    if category is None:
        return True
    if hasattr(category, "requires_problem_master"):
        return bool(category.requires_problem_master)
    return not category.is_others


def visit_has_legacy_submit_details(visit: Visit) -> bool:
    return bool(
        visit.farmer_id
        and visit.crop_id
        and visit.latitude is not None
        and visit.longitude is not None
    )


def visit_has_field_visit_details(visit: Visit) -> bool:
    name = (visit.farmer_name or "").strip()
    if not name and visit.farmer_id:
        name = (visit.farmer.name or "").strip()
    phone = _normalize_phone(visit.farmer_phone)
    if not phone and visit.farmer_id:
        phone = _normalize_phone(visit.farmer.phone)
    acreage = visit.land_area
    if acreage is None and visit.field_id and visit.field.land_size is not None:
        acreage = float(visit.field.land_size)
    description = (visit.problem_description or visit.problem_seen or "").strip()
    master_ok = True
    if visit.problem_category_id:
        cat = visit.problem_category
        if category_requires_master(cat) and not visit.problem_master_id:
            master_ok = False
    else:
        master_ok = False
    return bool(
        name
        and phone
        and visit.village_id
        and visit.crop_id
        and acreage is not None
        and acreage > 0
        and visit.problem_category_id
        and description
        and master_ok
    )


def visit_has_submitted_details(visit: Visit) -> bool:
    return visit_has_legacy_submit_details(visit) or visit_has_field_visit_details(
        visit
    )


def _get_category(data: dict) -> ProblemCategory | None:
    category = data.get("problem_category")
    if isinstance(category, ProblemCategory):
        return category
    category_id = data.get("problem_category_id") or category
    if category_id in (None, ""):
        return None
    try:
        return ProblemCategory.objects.get(pk=category_id, is_active=True)
    except ProblemCategory.DoesNotExist:
        return None


def _get_master(data: dict) -> ProblemMaster | None:
    master = data.get("problem_master") or data.get("problem_subcategory")
    if isinstance(master, ProblemMaster):
        return master
    master_id = (
        data.get("problem_master_id")
        or data.get("problem_subcategory_id")
        or master
    )
    if master_id in (None, ""):
        return None
    try:
        return ProblemMaster.objects.get(pk=master_id, is_active=True)
    except ProblemMaster.DoesNotExist:
        return None


def visit_data_has_legacy_submit_fields(data: dict) -> bool:
    farmer = data.get("farmer")
    farmer_id = getattr(farmer, "pk", farmer)
    crop = data.get("crop")
    crop_id = getattr(crop, "pk", crop)
    return bool(
        farmer_id
        and crop_id
        and data.get("latitude") is not None
        and data.get("longitude") is not None
    )


def visit_data_has_field_visit_fields(data: dict) -> bool:
    farmer = data.get("farmer")
    farmer_name = (data.get("farmer_name") or "").strip()
    if not farmer_name and farmer is not None:
        farmer_name = getattr(farmer, "name", "") or ""
    phone = _resolve_phone(data, farmer)
    village_id = _resolve_pk(data, "village", "village_id")
    crop_id = _resolve_pk(data, "crop", "crop_id")
    acreage = _positive_float(data.get("land_area", data.get("acreage")))
    category = _get_category(data)
    description = _resolve_problem_description(data)
    master = _get_master(data)
    master_ok = True
    if category and category_requires_master(category):
        master_ok = master is not None
    return bool(
        farmer_name
        and phone
        and village_id
        and crop_id
        and acreage is not None
        and category
        and description
        and master_ok
    )


def validate_field_visit_submit_data(data: dict) -> None:
    errors: dict[str, str] = {}

    farmer = data.get("farmer")
    farmer_name = (data.get("farmer_name") or "").strip()
    if not farmer_name and farmer is not None:
        farmer_name = (getattr(farmer, "name", "") or "").strip()
        data.setdefault("farmer_name", farmer_name)
    if not farmer_name:
        errors["farmer_name"] = "Farmer name is required."

    phone = _resolve_phone(data, farmer)
    if not phone:
        errors["farmer_phone"] = "Phone number is required."
    elif len(phone) < 10:
        errors["farmer_phone"] = "Enter a valid phone number (at least 10 digits)."
    else:
        data["farmer_phone"] = phone

    age_raw = data.get("farmer_age", data.get("age"))
    if age_raw not in (None, ""):
        try:
            age = int(age_raw)
            if age < 1 or age > 120:
                raise ValueError
            data["farmer_age"] = age
        except (TypeError, ValueError):
            errors["farmer_age"] = "Age must be between 1 and 120."

    village_id = _resolve_pk(data, "village", "village_id")
    if not village_id:
        errors["village"] = "Village is required."
    elif not Village.objects.filter(pk=village_id, is_active=True).exists():
        errors["village"] = "Invalid or inactive village."

    crop_id = _resolve_pk(data, "crop", "crop_id")
    if not crop_id:
        errors["crop"] = "Crop is required."

    acreage = _positive_float(data.get("land_area", data.get("acreage")))
    if acreage is None:
        errors["acreage"] = "Acreage is required and must be greater than 0."
    else:
        data["land_area"] = acreage

    category = _get_category(data)
    if not category:
        errors["problem_category"] = "Problem category is required."
    else:
        data["problem_category"] = category

    description = _resolve_problem_description(data)
    if not description:
        errors["problem_description"] = "Problem description is required."
    else:
        data["problem_description"] = description
        data["problem_seen"] = description

    master = _get_master(data)
    if category and category_requires_master(category):
        if not master:
            msg = "Problem subcategory is required for this category."
            errors["problem_subcategory"] = msg
            errors["problem_master"] = msg
        elif master.category_id != category.id:
            msg = "Problem subcategory does not belong to the selected category."
            errors["problem_subcategory"] = msg
            errors["problem_master"] = msg
        else:
            crop_id = getattr(data.get("crop"), "pk", data.get("crop_id") or data.get("crop"))
            if master.crop_id and crop_id and master.crop_id != int(crop_id):
                msg = "Problem subcategory is not available for the selected crop."
                errors["problem_subcategory"] = msg
                errors["problem_master"] = msg
            data["problem_master"] = master
            data["problem_subcategory"] = master
    elif master:
        if category and master.category_id != category.id:
            msg = "Problem subcategory does not belong to the selected category."
            errors["problem_subcategory"] = msg
            errors["problem_master"] = msg
        data["problem_master"] = master
        data["problem_subcategory"] = master
    else:
        data["problem_master"] = None
        data["problem_subcategory"] = None

    if errors:
        raise serializers.ValidationError(errors)


def validate_visit_submit_data(data: dict, raw: dict | None = None) -> None:
    if visit_data_has_legacy_submit_fields(data):
        return
    merge_field_visit_request_aliases(data, raw)
    validate_field_visit_submit_data(data)


def submitted_visit_filter() -> Q:
    legacy = Q(
        farmer_id__isnull=False,
        crop_id__isnull=False,
        latitude__isnull=False,
        longitude__isnull=False,
    )
    field_visit = Q(
        crop_id__isnull=False,
        village_id__isnull=False,
        problem_category_id__isnull=False,
        land_area__gt=0,
    ) & ~Q(problem_description="") & ~Q(problem_description__isnull=True)
    return legacy | field_visit


def submitted_visits_qs(base: QuerySet | None = None) -> QuerySet:
    qs = base if base is not None else Visit.objects.all()
    return qs.filter(submitted_visit_filter())


def incomplete_visit_filter() -> Q:
    return ~submitted_visit_filter()


def incomplete_visits_qs(base: QuerySet | None = None) -> QuerySet:
    qs = base if base is not None else Visit.objects.all()
    return qs.filter(incomplete_visit_filter())
