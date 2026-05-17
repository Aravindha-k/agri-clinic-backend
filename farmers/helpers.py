"""Shared helpers for farmer list, audit, and serializers."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from django.db.models import Q


def parse_gps_location(gps_location: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Parse Farmer.gps_location \"lat,lng\" into floats."""
    if not gps_location:
        return None, None
    parts = str(gps_location).split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except (ValueError, TypeError):
        return None, None


def is_e2e_test_farmer(farmer: Any) -> bool:
    """
    Heuristic for automated E2E / smoke-test farmer rows (read-only flag).
    Does not mutate data.
    """
    name = (getattr(farmer, "name", None) or "").strip()
    code = (getattr(farmer, "farmer_code", None) or "").strip()
    if name.startswith("Test Farmer"):
        return True
    lowered = name.lower()
    if "e2e" in lowered or "e2e" in code.lower():
        return True
    return False


def e2e_test_farmer_filter():
    """Q object matching E2E / smoke-test farmers."""
    return (
        Q(name__startswith="Test Farmer")
        | Q(name__icontains="e2e")
        | Q(farmer_code__icontains="e2e")
    )


def farmers_directory_queryset():
    """All farmer master records (not filtered by visits or is_active)."""
    from masters.models import Farmer

    return Farmer.objects.all()


def active_farmers_queryset():
    """Production farmers shown on admin dashboard KPIs."""
    from masters.models import Farmer

    return Farmer.objects.filter(is_active=True)
