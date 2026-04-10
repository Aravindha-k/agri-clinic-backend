"""
farmers/services.py
────────────────────
Business logic for farmer management.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.contrib.auth.models import User
from django.db import transaction

from masters.models import Farmer, FarmerField, FieldCrop

logger = logging.getLogger(__name__)


class FarmerServiceError(Exception):
    """Raised for farmer domain business rule violations."""


# ──────────────────────────────────────────────────────────────
# Farmer CRUD
# ──────────────────────────────────────────────────────────────


@transaction.atomic
def create_farmer(
    *,
    name: str,
    phone: str,
    district_id: Optional[int] = None,
    village_id: Optional[int] = None,
    address: str = "",
    total_land_area: Optional[float] = None,
    irrigation_type: str = "",
    soil_type: str = "",
    gps_location: str = "",
    assigned_employee: Optional[User] = None,
    created_by: Optional[User] = None,
    notes: str = "",
) -> Farmer:
    """
    Register a new farmer.
    Raises FarmerServiceError if phone is already registered.
    """
    if Farmer.objects.filter(phone=phone, is_active=True).exists():
        raise FarmerServiceError(
            f"A farmer with phone number '{phone}' already exists."
        )

    farmer = Farmer.objects.create(
        name=name,
        phone=phone,
        district_id=district_id,
        village_id=village_id,
        address=address,
        total_land_area=total_land_area,
        irrigation_type=irrigation_type,
        soil_type=soil_type,
        gps_location=gps_location,
        assigned_employee=assigned_employee,
        created_by_employee=created_by,
        is_active=True,
    )
    logger.info(
        "Farmer created: %s (%s) by user_id=%s",
        farmer.farmer_code,
        name,
        created_by.pk if created_by else "system",
    )
    return farmer


@transaction.atomic
def update_farmer(
    *,
    farmer: Farmer,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    district_id: Optional[int] = None,
    village_id: Optional[int] = None,
    address: Optional[str] = None,
    total_land_area: Optional[float] = None,
    irrigation_type: Optional[str] = None,
    soil_type: Optional[str] = None,
    gps_location: Optional[str] = None,
    assigned_employee: Optional[User] = None,
) -> Farmer:
    """Partially update a farmer record."""
    if phone and phone != farmer.phone:
        if (
            Farmer.objects.filter(phone=phone, is_active=True)
            .exclude(pk=farmer.pk)
            .exists()
        ):
            raise FarmerServiceError(
                f"Phone number '{phone}' is already registered to another farmer."
            )
        farmer.phone = phone

    if name is not None:
        farmer.name = name
    if district_id is not None:
        farmer.district_id = district_id
    if village_id is not None:
        farmer.village_id = village_id
    if address is not None:
        farmer.address = address
    if total_land_area is not None:
        farmer.total_land_area = total_land_area
    if irrigation_type is not None:
        farmer.irrigation_type = irrigation_type
    if soil_type is not None:
        farmer.soil_type = soil_type
    if gps_location is not None:
        farmer.gps_location = gps_location
    if assigned_employee is not None:
        farmer.assigned_employee = assigned_employee

    farmer.save()
    logger.info("Farmer updated: %s", farmer.farmer_code)
    return farmer


def deactivate_farmer(*, farmer: Farmer, deleted_by: Optional[User] = None) -> Farmer:
    """Soft-delete a farmer (set is_active=False)."""
    farmer.is_active = False
    farmer.save(update_fields=["is_active", "updated_at"])
    logger.info(
        "Farmer deactivated: %s by user_id=%s",
        farmer.farmer_code,
        deleted_by.pk if deleted_by else "system",
    )
    return farmer


def restore_farmer(*, farmer: Farmer) -> Farmer:
    farmer.is_active = True
    farmer.save(update_fields=["is_active", "updated_at"])
    logger.info("Farmer restored: %s", farmer.farmer_code)
    return farmer


# ──────────────────────────────────────────────────────────────
# FarmerField CRUD
# ──────────────────────────────────────────────────────────────


@transaction.atomic
def create_farmer_field(
    *,
    farmer: Farmer,
    land_name: str,
    area_acres: Optional[float] = None,
    irrigation_type: str = "",
    soil_type: str = "",
    gps_location: str = "",
    created_by: Optional[User] = None,
) -> FarmerField:
    field = FarmerField.objects.create(
        farmer=farmer,
        land_name=land_name,
        area_acres=area_acres,
        irrigation_type=irrigation_type,
        soil_type=soil_type,
        gps_location=gps_location,
        created_by_employee=created_by,
        is_active=True,
    )
    logger.info("FarmerField created: %s for farmer %s", field.pk, farmer.farmer_code)
    return field


# ──────────────────────────────────────────────────────────────
# FieldCrop CRUD
# ──────────────────────────────────────────────────────────────


@transaction.atomic
def assign_crop_to_field(
    *,
    field: FarmerField,
    crop_id: int,
    crop_name: str = "",
    season: str = "",
    sowing_date=None,
    expected_harvest_date=None,
) -> FieldCrop:
    field_crop = FieldCrop.objects.create(
        land=field,
        crop_id=crop_id,
        crop_name=crop_name,
        season=season,
        sowing_date=sowing_date,
        expected_harvest_date=expected_harvest_date,
        is_active=True,
    )
    logger.info("FieldCrop created: crop_id=%s on field_id=%s", crop_id, field.pk)
    return field_crop
