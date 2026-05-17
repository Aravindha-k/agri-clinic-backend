"""
farmers/selectors.py
─────────────────────
Read-only query logic for the Farmer domain.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.contrib.auth.models import User
from django.db.models import Count, QuerySet

from masters.models import Farmer, FarmerField, FieldCrop

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Farmer queries
# ──────────────────────────────────────────────────────────────


def get_farmers(
    *,
    is_active: Optional[bool] = None,
    district_id: Optional[int] = None,
    village_id: Optional[int] = None,
    assigned_employee_id: Optional[int] = None,
    created_by_id: Optional[int] = None,
    search: Optional[str] = None,
    include_visit_count: bool = False,
) -> QuerySet:
    """
    Return a filtered queryset of Farmer objects.

    Pass is_active=None to include all farmers regardless of status.
    """
    qs = Farmer.objects.select_related(
        "village", "district", "assigned_employee", "created_by_employee"
    )

    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    if district_id:
        qs = qs.filter(district_id=district_id)

    if village_id:
        qs = qs.filter(village_id=village_id)

    if assigned_employee_id:
        qs = qs.filter(assigned_employee_id=assigned_employee_id)

    if created_by_id:
        qs = qs.filter(created_by_employee_id=created_by_id)

    if search:
        from django.db.models import Q

        qs = qs.filter(
            Q(name__icontains=search)
            | Q(phone__icontains=search)
            | Q(farmer_code__icontains=search)
            | Q(village__name__icontains=search)
        )

    if include_visit_count:
        qs = qs.annotate(visit_count=Count("visits"))

    return qs.order_by("name")


def get_farmer_by_id(farmer_id: int) -> Optional[Farmer]:
    return (
        Farmer.objects.select_related(
            "village", "district", "assigned_employee", "created_by_employee"
        )
        .filter(pk=farmer_id)
        .first()
    )


def get_farmer_by_code(farmer_code: str) -> Optional[Farmer]:
    return (
        Farmer.objects.select_related("village", "district")
        .filter(farmer_code=farmer_code)
        .first()
    )


def get_farmer_by_phone(phone: str) -> Optional[Farmer]:
    return Farmer.objects.filter(phone=phone).first()


# ──────────────────────────────────────────────────────────────
# Farmer field & crop queries
# ──────────────────────────────────────────────────────────────


def get_fields_for_farmer(farmer: Farmer, is_active: bool = True) -> QuerySet:
    qs = FarmerField.objects.select_related("farmer").filter(farmer=farmer)
    if is_active:
        qs = qs.filter(is_active=True)
    return qs.order_by("land_name")


def get_crops_for_field(field: FarmerField, is_active: bool = True) -> QuerySet:
    qs = FieldCrop.objects.select_related("land", "crop").filter(land=field)
    if is_active:
        qs = qs.filter(is_active=True)
    return qs


# ──────────────────────────────────────────────────────────────
# Aggregates
# ──────────────────────────────────────────────────────────────


def get_farmer_count() -> int:
    return Farmer.objects.count()
