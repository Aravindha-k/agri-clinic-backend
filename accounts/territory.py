"""
Canonical employee territory service.

Source of truth: village-level EmployeeLocationAssignment rows that are
active AND operational. Operational identity is Employee ↔ Village.

District, taluk, and firka are legacy and must not be used for operational
scoping. EmployeeProfile.district / EmployeeProfile.village are also legacy.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.models import Village


class TerritoryValidationError(serializers.ValidationError):
    """Raised when a village/farmer is outside the employee's territory."""


def user_requires_territory_scope(user) -> bool:
    """Field employees are territory-scoped. Staff/admin/privileged are not."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    from visits.access import is_privileged_user

    return not is_privileged_user(user)


def _profile_for(employee) -> EmployeeProfile | None:
    if employee is None:
        return None
    if isinstance(employee, EmployeeProfile):
        return employee
    return getattr(employee, "employee_profile", None)


def operational_assignment_queryset(employee=None):
    """
    Active village-level assignments.

    Fail-closed: district-only / taluk-only / incomplete village rows are
    excluded. Zero matching rows means no territory. Village does not need
    District or Taluk.
    """
    qs = EmployeeLocationAssignment.objects.filter(
        is_active=True,
        is_operational=True,
        village_id__isnull=False,
        village__isnull=False,
        village__is_active=True,
    ).select_related("village")
    profile = _profile_for(employee) if employee is not None else None
    if employee is not None:
        if profile is None:
            return qs.none()
        qs = qs.filter(employee_id=profile.id)
    return qs


def get_employee_assigned_village_ids(employee) -> frozenset[int]:
    """Operational village IDs. Empty frozenset if none — never 'all villages'."""
    profile = _profile_for(employee)
    if profile is None:
        return frozenset()
    return frozenset(
        operational_assignment_queryset(profile).values_list("village_id", flat=True)
    )


def village_in_employee_territory(employee, village) -> bool:
    village_id = getattr(village, "pk", village)
    if village_id in (None, ""):
        return False
    return int(village_id) in get_employee_assigned_village_ids(employee)


def assert_village_in_employee_territory(employee, village) -> None:
    village_id = getattr(village, "pk", village)
    assigned = get_employee_assigned_village_ids(employee)
    if not assigned:
        raise TerritoryValidationError(
            {
                "village": (
                    "No territory assigned. Contact your administrator."
                )
            }
        )
    if village_id in (None, ""):
        raise TerritoryValidationError({"village": "Village is required."})
    if int(village_id) not in assigned:
        raise TerritoryValidationError(
            {"village": "Village is outside your assigned territory."}
        )


def assert_farmer_in_employee_territory(employee, farmer) -> None:
    if farmer is None:
        raise TerritoryValidationError({"farmer": "Farmer is required."})
    if not getattr(farmer, "is_active", True):
        raise TerritoryValidationError(
            {
                "farmer": (
                    "This farmer is archived and cannot be used for a new visit."
                )
            }
        )
    assigned = get_employee_assigned_village_ids(employee)
    if not assigned:
        raise TerritoryValidationError(
            {
                "farmer": (
                    "No territory assigned. Contact your administrator."
                )
            }
        )
    if farmer.village_id not in assigned:
        raise TerritoryValidationError(
            {"farmer": "Farmer is outside your assigned territory."}
        )


def operational_villages_for_employee(employee) -> list[Village]:
    village_ids = get_employee_assigned_village_ids(employee)
    if not village_ids:
        return []
    return list(
        Village.objects.filter(pk__in=village_ids).order_by("name")
    )


def build_employee_territory_payload(employee) -> dict[str, Any]:
    """Assigned villages for Mobile. Empty list if unassigned (fail-closed)."""
    villages = [
        {
            "id": village.id,
            "name": village.name,
            "name_ta": village.name_ta or "",
            "is_active": village.is_active,
        }
        for village in operational_villages_for_employee(employee)
    ]
    return {"villages": villages}


def filter_districts_for_user(queryset, user):
    """District is not operational. Field employees see none; admin unscoped."""
    if not user_requires_territory_scope(user):
        return queryset
    return queryset.none()


def filter_taluks_for_user(queryset, user):
    """Taluk is not operational. Field employees see none; admin unscoped."""
    if not user_requires_territory_scope(user):
        return queryset
    return queryset.none()


def filter_villages_for_user(queryset, user):
    """Scope a Village queryset for field employees. Admin/staff unchanged."""
    if not user_requires_territory_scope(user):
        return queryset
    village_ids = get_employee_assigned_village_ids(user)
    if not village_ids:
        return queryset.none()
    return queryset.filter(pk__in=village_ids)


def filter_farmers_for_user(queryset, user):
    """
    Operational farmer directory for field employees:
    active farmers whose village is in assigned territory.
    Fail-closed when the employee has zero assigned villages.
    """
    if not user_requires_territory_scope(user):
        return queryset
    village_ids = get_employee_assigned_village_ids(user)
    if not village_ids:
        return queryset.none()
    return queryset.filter(is_active=True, village_id__in=village_ids)
