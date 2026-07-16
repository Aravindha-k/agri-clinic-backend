"""Canonical farmer resolution for field-visit submit.

Match order (locked):
1. explicit farmer_id
2. normalized phone
3. controlled farmer creation (when allowed)

Never link by farmer name alone.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.models import User
from rest_framework import serializers

from masters.models import Farmer, Village
from visits.farmer_inline import get_or_create_farmer_for_field_visit
from visits.field_visit import _normalize_phone

logger = logging.getLogger(__name__)


class FarmerResolutionError(serializers.ValidationError):
    """Raised when farmer cannot be resolved safely."""


def resolve_farmer_for_visit(
    data: dict[str, Any],
    *,
    employee: User | None,
    create_if_missing: bool = True,
) -> Farmer | None:
    """
    Resolve farmer into ``data['farmer']`` and snapshot name/phone/district/village.

    Mutates ``data`` in place. Returns the resolved Farmer or None.
    """
    farmer = _coerce_farmer(data.get("farmer"))
    village = _coerce_village(data.get("village"))
    if village is not None:
        data["village"] = village

    if farmer is None:
        field = data.get("field")
        if field is not None and getattr(field, "farmer_id", None):
            farmer = field.farmer

    if farmer is None:
        phone = _normalize_phone(
            data.get("farmer_phone")
            or data.get("phone_number")
            or data.get("phone")
            or data.get("mobile")
        )
        if phone:
            farmer = (
                Farmer.objects.filter(phone=phone, is_active=True)
                .order_by("id")
                .first()
            )
            if farmer is None:
                # Historical rows may store un-normalized phones.
                farmer = Farmer.objects.filter(phone=phone).order_by("id").first()

    # Intentionally no name-only match.

    if farmer is None and create_if_missing:
        phone = _normalize_phone(
            data.get("farmer_phone")
            or data.get("phone_number")
            or data.get("phone")
            or data.get("mobile")
        )
        name = (data.get("farmer_name") or "").strip()
        if phone and name and village is not None:
            farmer, created = get_or_create_farmer_for_field_visit(
                name=name,
                phone=phone,
                village=village,
                created_by=employee,
            )
            if created:
                logger.info(
                    "Created farmer id=%s phone=%s for field visit",
                    farmer.pk,
                    phone,
                )
        elif name and not phone:
            raise FarmerResolutionError(
                {
                    "farmer_phone": (
                        "Phone is required to create or link a farmer. "
                        "Name-only matching is not allowed."
                    )
                }
            )

    if farmer is not None:
        data["farmer"] = farmer
        data["farmer_name"] = farmer.name
        data["farmer_phone"] = farmer.phone
        data.setdefault("district", farmer.district)
        if not data.get("village") and farmer.village_id:
            data["village"] = farmer.village
    return farmer


def _coerce_farmer(value: Any) -> Farmer | None:
    if value is None or isinstance(value, Farmer):
        return value
    try:
        return Farmer.objects.get(pk=value)
    except (Farmer.DoesNotExist, TypeError, ValueError):
        return None


def _coerce_village(value: Any) -> Village | None:
    if value is None or isinstance(value, Village):
        return value
    try:
        return Village.objects.get(pk=value)
    except (Village.DoesNotExist, TypeError, ValueError):
        return None
