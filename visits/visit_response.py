"""Shared visit/farmer payload helpers for mobile and admin APIs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from visits.models import Visit

from utils.photo_urls import build_profile_photo_url

# Use on all visit list/detail querysets so farmer/crop are not blank when FK exists.
VISIT_LIST_SELECT_RELATED = (
    "employee",
    "employee__employee_profile",
    "district",
    "village",
    "crop",
    "farmer",
    "farmer__village",
    "farmer__district",
    "field",
    "problem_category",
    "problem_master",
    "problem_master__category",
)


def crop_display_name(visit: Visit) -> str:
    if not visit.crop_id:
        return ""
    crop = visit.crop
    if crop.name_ta:
        return f"{crop.name_en} / {crop.name_ta}"
    return crop.name_en or ""


def build_visit_farmer_block(
    visit: Visit, request=None
) -> Optional[Dict[str, Any]]:
    """
    Nested farmer object for visit responses (mobile + admin).
    Includes both `mobile` and `phone` (same value) for client compatibility.
    """
    profile_photo_url = None
    if visit.farmer_id:
        name = visit.farmer.name
        mobile = visit.farmer.phone
        profile_photo_url = build_profile_photo_url(
            request, visit.farmer.profile_photo
        )
        village = ""
        if visit.farmer.village_id:
            village = visit.farmer.village.name
        elif visit.village_id:
            village = visit.village.name
    elif visit.farmer_name or visit.farmer_phone:
        name = visit.farmer_name or ""
        mobile = visit.farmer_phone or ""
        village = visit.village.name if visit.village_id else ""
    else:
        return None

    acreage = None
    if visit.land_area is not None:
        acreage = visit.land_area
    elif visit.field_id and visit.field.land_size is not None:
        acreage = float(visit.field.land_size)

    return {
        "id": visit.farmer_id,
        "name": name or "",
        "mobile": mobile or "",
        "phone": mobile or "",
        "age": visit.farmer_age,
        "village": village or "",
        "village_id": visit.village_id,
        "profile_photo_url": profile_photo_url,
        "crop_name": crop_display_name(visit),
        "acreage": acreage,
        "land_area": acreage,
        "latitude": visit.latitude,
        "longitude": visit.longitude,
    }


def build_field_visit_problem_block(visit: Visit) -> dict | None:
    if not visit.problem_category_id and not (visit.problem_description or visit.problem_seen):
        return None
    block = {
        "problem_category_id": visit.problem_category_id,
        "problem_master_id": visit.problem_master_id,
        "problem_subcategory_id": visit.problem_master_id,
        "problem_description": visit.problem_description or visit.problem_seen or "",
    }
    if visit.problem_category_id:
        cat = visit.problem_category
        block["problem_category"] = {
            "id": cat.id,
            "code": cat.code,
            "name": cat.name,
        }
    if visit.problem_master_id:
        master = visit.problem_master
        sub = {"id": master.id, "name": master.name}
        block["problem_master"] = sub
        block["problem_subcategory"] = sub
    return block


def build_field_visit_snapshot(visit: Visit) -> dict:
    """Canonical farmer/crop/problem snapshot stored on the visit row."""
    farmer_block = build_visit_farmer_block(visit) or {}
    return {
        "farmer_name": visit.farmer_name or farmer_block.get("name", ""),
        "age": visit.farmer_age,
        "phone_number": visit.farmer_phone or farmer_block.get("phone", ""),
        "village_id": visit.village_id,
        "village_name": farmer_block.get("village") or "",
        "crop_id": visit.crop_id,
        "crop_name": crop_display_name(visit),
        "acreage": visit.land_area,
        **(build_field_visit_problem_block(visit) or {}),
    }


def build_visit_employee_block(visit: Visit, request=None) -> Dict[str, Any]:
    profile = getattr(visit.employee, "employee_profile", None)
    updated_at = profile.profile_photo_updated_at if profile else None
    return {
        "id": visit.employee_id,
        "username": visit.employee.username,
        "employee_id": profile.employee_id if profile else None,
        "phone": profile.phone if profile else "",
        "profile_photo_url": build_profile_photo_url(
            request, profile.profile_photo if profile else None
        ),
        "profile_photo_updated_at": updated_at.isoformat() if updated_at else None,
    }


def reload_visit(pk: int) -> Visit:
    return Visit.objects.select_related(*VISIT_LIST_SELECT_RELATED).get(pk=pk)
