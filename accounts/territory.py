"""
Canonical employee territory service.

Source of truth: village-level EmployeeLocationAssignment rows that are
active AND operational. District and taluk are always derived from:

    Village → Taluk → District

EmployeeProfile.district / EmployeeProfile.village are legacy and must not
be used for operational scoping.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
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
    Active village-level assignments with a valid live hierarchy.

    Fail-closed: district-only / taluk-only / incomplete village rows are
    excluded. Zero matching rows means no territory.
    """
    qs = EmployeeLocationAssignment.objects.filter(
        is_active=True,
        is_operational=True,
        village_id__isnull=False,
        village__isnull=False,
        village__is_active=True,
        village__taluk__isnull=False,
        village__taluk__is_active=True,
        village__taluk__district__is_active=True,
    ).select_related("village", "village__taluk", "village__taluk__district", "district", "taluk")
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


def get_employee_assigned_taluk_ids(employee) -> frozenset[int]:
    village_ids = get_employee_assigned_village_ids(employee)
    if not village_ids:
        return frozenset()
    return frozenset(
        Village.objects.filter(pk__in=village_ids, taluk_id__isnull=False).values_list(
            "taluk_id", flat=True
        )
    )


def get_employee_assigned_district_ids(employee) -> frozenset[int]:
    village_ids = get_employee_assigned_village_ids(employee)
    if not village_ids:
        return frozenset()
    return frozenset(
        Village.objects.filter(
            pk__in=village_ids, taluk__isnull=False, taluk__district_id__isnull=False
        ).values_list("taluk__district_id", flat=True)
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
        Village.objects.filter(pk__in=village_ids)
        .select_related("taluk", "taluk__district", "district")
        .order_by("taluk__district__name", "taluk__name", "name")
    )


def build_employee_territory_payload(employee) -> dict[str, Any]:
    """Nested districts → taluks → villages for Mobile. Empty if unassigned."""
    villages = operational_villages_for_employee(employee)
    grouped: dict[int, dict[str, Any]] = {}
    for village in villages:
        taluk = village.taluk
        if taluk is None or taluk.district_id is None:
            continue
        district = taluk.district
        district_block = grouped.setdefault(
            district.id,
            {
                "id": district.id,
                "name": district.name,
                "taluks": {},
            },
        )
        taluk_block = district_block["taluks"].setdefault(
            taluk.id,
            {
                "id": taluk.id,
                "name": taluk.name,
                "villages": [],
            },
        )
        taluk_block["villages"].append({"id": village.id, "name": village.name})

    districts = []
    for district_id, district_block in grouped.items():
        taluks = list(district_block["taluks"].values())
        for taluk_block in taluks:
            taluk_block["villages"].sort(key=lambda row: row["name"].lower())
        taluks.sort(key=lambda row: row["name"].lower())
        districts.append(
            {
                "id": district_block["id"],
                "name": district_block["name"],
                "taluks": taluks,
            }
        )
    districts.sort(key=lambda row: row["name"].lower())
    return {"districts": districts}


def filter_districts_for_user(queryset, user):
    """Scope a District queryset for field employees. Admin/staff unchanged."""
    if not user_requires_territory_scope(user):
        return queryset
    district_ids = get_employee_assigned_district_ids(user)
    if not district_ids:
        return queryset.none()
    return queryset.filter(pk__in=district_ids)


def filter_taluks_for_user(queryset, user):
    """Scope a Taluk queryset for field employees. Admin/staff unchanged."""
    if not user_requires_territory_scope(user):
        return queryset
    taluk_ids = get_employee_assigned_taluk_ids(user)
    if not taluk_ids:
        return queryset.none()
    return queryset.filter(pk__in=taluk_ids)


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
