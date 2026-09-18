"""Canonical farmer resolution for field-visit submit.

Match order (locked):
1. explicit farmer_id
2. normalized phone among ACTIVE farmers
3. controlled farmer creation (when allowed)

Never link by farmer name alone.
Never attach a new visit to an archived farmer via phone.
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
    from accounts.territory import (
        assert_farmer_in_employee_territory,
        assert_village_in_employee_territory,
        user_requires_territory_scope,
    )

    farmer = _coerce_farmer(data.get("farmer"))
    village = _coerce_village(data.get("village"))
    if village is not None:
        data["village"] = village
        if village.taluk_id and village.taluk and village.taluk.district_id:
            data["district"] = village.taluk.district
        elif village.district_id:
            data["district"] = village.district

    scope_territory = user_requires_territory_scope(employee)
    if scope_territory and village is not None:
        assert_village_in_employee_territory(employee, village)

    if farmer is None:
        field = data.get("field")
        if field is not None and getattr(field, "farmer_id", None):
            farmer = field.farmer

    phone = _normalize_phone(
        data.get("farmer_phone")
        or data.get("phone_number")
        or data.get("phone")
        or data.get("mobile")
    )

    if farmer is None and phone:
        farmer = (
            Farmer.objects.filter(phone=phone, is_active=True)
            .order_by("id")
            .first()
        )
        if farmer is None:
            archived = Farmer.objects.filter(phone=phone, is_active=False).exists()
            if archived:
                raise FarmerResolutionError(
                    {
                        "farmer": (
                            "This farmer is archived and cannot be used for a new visit."
                        )
                    }
                )

    # Intentionally no name-only match.

    if farmer is not None:
        if not farmer.is_active:
            raise FarmerResolutionError(
                {
                    "farmer": (
                        "This farmer is archived and cannot be used for a new visit."
                    )
                }
            )
        if scope_territory:
            assert_farmer_in_employee_territory(employee, farmer)

    if farmer is None and create_if_missing:
        name = (data.get("farmer_name") or "").strip()
        if phone and name and village is not None:
            if scope_territory:
                assert_village_in_employee_territory(employee, village)
            try:
                farmer, created = get_or_create_farmer_for_field_visit(
                    name=name,
                    phone=phone,
                    village=village,
                    created_by=employee,
                )
            except ValueError as exc:
                raise FarmerResolutionError(
                    {
                        "farmer": (
                            "This farmer is archived and cannot be used for a new visit."
                        )
                    }
                ) from exc
            if created:
                logger.info(
                    "Created farmer id=%s phone=%s for field visit",
                    farmer.pk,
                    phone,
                )
            elif not farmer.is_active:
                raise FarmerResolutionError(
                    {
                        "farmer": (
                            "This farmer is archived and cannot be used for a new visit."
                        )
                    }
                )
            elif scope_territory:
                assert_farmer_in_employee_territory(employee, farmer)
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
        if village is None and farmer.village_id:
            data["village"] = farmer.village
            village = farmer.village
        if village is not None and village.taluk_id:
            data.setdefault("district", village.taluk.district)
        else:
            data.setdefault("district", farmer.district)
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
        return (
            Village.objects.select_related("taluk", "taluk__district", "district")
            .filter(pk=value)
            .first()
        )
    except (TypeError, ValueError):
        return None
