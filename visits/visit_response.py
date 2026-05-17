"""Shared visit/farmer payload helpers for mobile and admin APIs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from visits.models import Visit

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
)


def crop_display_name(visit: Visit) -> str:
    if not visit.crop_id:
        return ""
    crop = visit.crop
    if crop.name_ta:
        return f"{crop.name_en} / {crop.name_ta}"
    return crop.name_en or ""


def build_visit_farmer_block(visit: Visit) -> Optional[Dict[str, Any]]:
    """
    Nested farmer object for visit responses (mobile + admin).
    Includes both `mobile` and `phone` (same value) for client compatibility.
    """
    if visit.farmer_id:
        name = visit.farmer.name
        mobile = visit.farmer.phone
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
        "village": village or "",
        "crop_name": crop_display_name(visit),
        "acreage": acreage,
        "land_area": acreage,
        "latitude": visit.latitude,
        "longitude": visit.longitude,
    }


def reload_visit(pk: int) -> Visit:
    return Visit.objects.select_related(*VISIT_LIST_SELECT_RELATED).get(pk=pk)
