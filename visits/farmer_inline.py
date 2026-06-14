"""Create or link farmers during field visit submit."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db import IntegrityError

from masters.models import Farmer, Village
from visits.field_visit import _normalize_phone


def get_or_create_farmer_for_field_visit(
    *,
    name: str,
    phone: str,
    village: Village,
    created_by: User | None = None,
) -> tuple[Farmer, bool]:
    """
    Return (farmer, created).
    Matches by normalized phone first, then creates a new active farmer.
    """
    phone_digits = _normalize_phone(phone)
    if not phone_digits:
        raise ValueError("phone required")

    existing = Farmer.objects.filter(phone=phone_digits).order_by("id").first()
    if existing:
        return existing, False

    district = village.district if village.district_id else None
    farmer = Farmer(
        name=(name or "").strip() or "Farmer",
        phone=phone_digits,
        village=village,
        district=district,
        is_active=True,
        created_by_employee=created_by if created_by and not created_by.is_staff else None,
    )
    if created_by and not created_by.is_staff:
        farmer.assigned_employee = created_by
    try:
        farmer.save()
    except IntegrityError:
        existing = Farmer.objects.filter(phone=phone_digits).order_by("id").first()
        if existing:
            return existing, False
        raise
    return farmer, True
