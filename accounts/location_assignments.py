"""
Employee location assignment service.

Administrative reference metadata only. Must not be used for authorization
or operational scoping.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from rest_framework import serializers

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.models import District, Taluk, Village
from utils.prefix_search import (
    EMPLOYEE_PROFILE_SEARCH_FIELDS,
    prefix_search_q,
    normalize_search_term,
)


class LocationAssignmentValidationError(serializers.ValidationError):
    """Raised when assignment payload fails hierarchy or master validation."""


# Compact list preview caps — counts in location_assignment_summary remain authoritative.
PREVIEW_DISTRICT_LIMIT = 2
PREVIEW_TALUK_LIMIT = 3
PREVIEW_VILLAGE_LIMIT = 3


def field_employee_queryset() -> QuerySet[EmployeeProfile]:
    """Field employees only — excludes staff/admin accounts."""
    return (
        EmployeeProfile.objects.filter(user__is_staff=False)
        .select_related("user", "district")
        .order_by("employee_id")
    )


def assignment_rows_for_employee(employee_id: int) -> QuerySet[EmployeeLocationAssignment]:
    return (
        EmployeeLocationAssignment.objects.filter(employee_id=employee_id, is_active=True)
        .select_related("district", "taluk", "village", "employee__user")
        .order_by("district__name", "taluk__name", "village__name")
    )


def annotate_assignment_counts(qs: QuerySet[EmployeeProfile]) -> QuerySet[EmployeeProfile]:
    """Attach district/taluk/village counts without loading all village rows."""
    active = Q(location_assignments__is_active=True)
    return qs.annotate(
        location_district_count=Count(
            "location_assignments__district",
            filter=active,
            distinct=True,
        ),
        location_taluk_count=Count(
            "location_assignments__taluk",
            filter=active & Q(location_assignments__taluk__isnull=False),
            distinct=True,
        ),
        location_village_count=Count(
            "location_assignments__village",
            filter=active & Q(location_assignments__village__isnull=False),
            distinct=True,
        ),
    )


def _distinct_district_count(rows: list[EmployeeLocationAssignment]) -> int:
    return len({r.district_id for r in rows})


def _distinct_taluk_count(rows: list[EmployeeLocationAssignment]) -> int:
    return len({r.taluk_id for r in rows if r.taluk_id})


def _distinct_village_count(rows: list[EmployeeLocationAssignment]) -> int:
    return len({r.village_id for r in rows if r.village_id})


def employee_summary_payload(profile: EmployeeProfile) -> dict[str, Any]:
    user = profile.user
    display_name = (user.first_name or user.username or profile.employee_id).strip()
    return {
        "id": profile.id,
        "employee_id": profile.employee_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": display_name,
        "is_active": profile.is_active_employee,
        "role": profile.role,
    }


def assignment_summary_from_rows(rows: list[EmployeeLocationAssignment]) -> dict[str, int]:
    return {
        "district_count": _distinct_district_count(rows),
        "taluk_count": _distinct_taluk_count(rows),
        "village_count": _distinct_village_count(rows),
    }


def _sorted_name_items(items: dict[int, str]) -> list[dict[str, Any]]:
    return [
        {"id": item_id, "name": name}
        for item_id, name in sorted(items.items(), key=lambda pair: pair[1].lower())
    ]


def assignment_preview_from_rows(
    rows: list[EmployeeLocationAssignment],
    *,
    district_limit: int = PREVIEW_DISTRICT_LIMIT,
    taluk_limit: int = PREVIEW_TALUK_LIMIT,
    village_limit: int = PREVIEW_VILLAGE_LIMIT,
) -> dict[str, list[dict[str, Any]]]:
    """Compact id/name preview for list rows — capped, counts remain authoritative."""
    districts: dict[int, str] = {}
    taluks: dict[int, str] = {}
    villages: dict[int, str] = {}

    for row in rows:
        if row.district_id and row.district_id not in districts:
            districts[row.district_id] = row.district.name
        if row.taluk_id and row.taluk_id not in taluks:
            taluks[row.taluk_id] = row.taluk.name
        if row.village_id and row.village_id not in villages:
            villages[row.village_id] = row.village.name

    return {
        "districts": _sorted_name_items(districts)[:district_limit],
        "taluks": _sorted_name_items(taluks)[:taluk_limit],
        "villages": _sorted_name_items(villages)[:village_limit],
    }


def assignment_previews_for_employees(
    employee_ids: list[int],
    *,
    district_limit: int = PREVIEW_DISTRICT_LIMIT,
    taluk_limit: int = PREVIEW_TALUK_LIMIT,
    village_limit: int = PREVIEW_VILLAGE_LIMIT,
) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """Batch preview lookup for one paginated list page — avoids N+1 detail requests."""
    if not employee_ids:
        return {}

    rows = (
        EmployeeLocationAssignment.objects.filter(
            employee_id__in=employee_ids,
            is_active=True,
        )
        .select_related("district", "taluk", "village")
        .order_by(
            "employee_id",
            "district__name",
            "taluk__name",
            "village__name",
        )
    )

    by_employee: dict[int, list[EmployeeLocationAssignment]] = defaultdict(list)
    for row in rows:
        by_employee[row.employee_id].append(row)

    return {
        employee_id: assignment_preview_from_rows(
            by_employee.get(employee_id, []),
            district_limit=district_limit,
            taluk_limit=taluk_limit,
            village_limit=village_limit,
        )
        for employee_id in employee_ids
    }


def group_assignments_for_response(
    rows: list[EmployeeLocationAssignment],
) -> list[dict[str, Any]]:
    """
    Group flat assignment rows into district → taluk → villages hierarchy.

    District-only rows appear as assignments with taluk=null and villages=[].
    Taluk-only rows appear with villages=[].
    """
    grouped: dict[tuple[int, int | None], dict[str, Any]] = {}

    for row in rows:
        key = (row.district_id, row.taluk_id)
        if key not in grouped:
            grouped[key] = {
                "district": {"id": row.district_id, "name": row.district.name},
                "taluk": (
                    {"id": row.taluk_id, "name": row.taluk.name}
                    if row.taluk_id
                    else None
                ),
                "villages": [],
            }
        if row.village_id:
            grouped[key]["villages"].append(
                {"id": row.village_id, "name": row.village.name}
            )

    result = list(grouped.values())
    for item in result:
        item["villages"].sort(key=lambda v: v["name"].lower())
    result.sort(
        key=lambda g: (
            g["district"]["name"].lower(),
            (g["taluk"] or {"name": ""})["name"].lower(),
        )
    )
    return result


def _validate_active_master(obj, label: str) -> None:
    if not obj.is_active:
        raise LocationAssignmentValidationError(
            {label: f"{label} '{obj.name}' is inactive and cannot be newly assigned."}
        )


def _validate_village(village: Village, district: District, taluk: Taluk | None) -> None:
    if village.taluk_id is None:
        raise LocationAssignmentValidationError(
            {
                "village_ids": (
                    f"Village '{village.name}' has no taluk and cannot be assigned."
                )
            }
        )
    if village.taluk_id != taluk.id:
        raise LocationAssignmentValidationError(
            {
                "village_ids": (
                    f"Village '{village.name}' does not belong to taluk "
                    f"'{taluk.name}'."
                )
            }
        )
    if village.taluk.district_id != district.id:
        raise LocationAssignmentValidationError(
            {
                "village_ids": (
                    f"Village '{village.name}' does not belong to district "
                    f"'{district.name}'."
                )
            }
        )
    _validate_active_master(village, "village")


def _validate_taluk(taluk: Taluk, district: District) -> None:
    if taluk.district_id != district.id:
        raise LocationAssignmentValidationError(
            {
                "taluk_id": (
                    f"Taluk '{taluk.name}' does not belong to district "
                    f"'{district.name}'."
                )
            }
        )
    _validate_active_master(taluk, "taluk")


def _validate_district(district: District) -> None:
    _validate_active_master(district, "district")


def expand_assignment_groups(
    assignment_groups: list[dict[str, Any]],
) -> list[tuple[int, int | None, int | None]]:
    """
    Expand hierarchy payload groups into normalized row tuples:
    (district_id, taluk_id|None, village_id|None).
    """
    rows: list[tuple[int, int | None, int | None]] = []
    seen: set[tuple[int, int | None, int | None]] = set()

    district_cache: dict[int, District] = {}
    taluk_cache: dict[int, Taluk] = {}
    village_cache: dict[int, Village] = {}

    for index, group in enumerate(assignment_groups):
        prefix = f"assignments[{index}]"
        district_id = group.get("district_id")
        taluk_id = group.get("taluk_id")
        village_ids = group.get("village_ids") or []

        if not district_id:
            raise LocationAssignmentValidationError(
                {prefix: "district_id is required for each assignment group."}
            )

        district = district_cache.get(district_id)
        if district is None:
            district = District.objects.filter(pk=district_id).first()
            if not district:
                raise LocationAssignmentValidationError(
                    {f"{prefix}.district_id": "District not found."}
                )
            district_cache[district_id] = district
        _validate_district(district)

        taluk = None
        if taluk_id:
            taluk = taluk_cache.get(taluk_id)
            if taluk is None:
                taluk = Taluk.objects.filter(pk=taluk_id).select_related("district").first()
                if not taluk:
                    raise LocationAssignmentValidationError(
                        {f"{prefix}.taluk_id": "Taluk not found."}
                    )
                taluk_cache[taluk_id] = taluk
            _validate_taluk(taluk, district)

        if village_ids:
            if not taluk_id:
                raise LocationAssignmentValidationError(
                    {
                        f"{prefix}.taluk_id": (
                            "taluk_id is required when village_ids are provided."
                        )
                    }
                )
            for village_id in village_ids:
                village = village_cache.get(village_id)
                if village is None:
                    village = (
                        Village.objects.filter(pk=village_id)
                        .select_related("taluk", "taluk__district")
                        .first()
                    )
                    if not village:
                        raise LocationAssignmentValidationError(
                            {
                                f"{prefix}.village_ids": (
                                    f"Village id {village_id} not found."
                                )
                            }
                        )
                    village_cache[village_id] = village
                _validate_village(village, district, taluk)
                key = (district.id, taluk.id, village.id)
                if key not in seen:
                    seen.add(key)
                    rows.append(key)
        elif taluk_id:
            key = (district.id, taluk.id, None)
            if key not in seen:
                seen.add(key)
                rows.append(key)
        else:
            key = (district.id, None, None)
            if key not in seen:
                seen.add(key)
                rows.append(key)

    return rows


@transaction.atomic
def replace_employee_location_assignments(
    *,
    employee: EmployeeProfile,
    assignment_groups: list[dict[str, Any]],
    actor: User | None = None,
) -> list[EmployeeLocationAssignment]:
    """
    Atomically replace all active assignments for an employee.

    Existing rows are hard-deleted and replaced with the validated final set.
    """
    expanded = expand_assignment_groups(assignment_groups)

    EmployeeLocationAssignment.objects.filter(employee=employee).delete()

    created: list[EmployeeLocationAssignment] = []
    for district_id, taluk_id, village_id in expanded:
        created.append(
            EmployeeLocationAssignment.objects.create(
                employee=employee,
                district_id=district_id,
                taluk_id=taluk_id,
                village_id=village_id,
                is_active=True,
                created_by=actor,
                updated_by=actor,
            )
        )
    return created


def filter_employees_for_assignment_list(
    qs: QuerySet[EmployeeProfile],
    *,
    employee_id: int | None = None,
    district_id: int | None = None,
    taluk_id: int | None = None,
    village_id: int | None = None,
    search: str | None = None,
) -> QuerySet[EmployeeProfile]:
    if employee_id:
        qs = qs.filter(pk=employee_id)
    if district_id:
        qs = qs.filter(
            location_assignments__district_id=district_id,
            location_assignments__is_active=True,
        )
    if taluk_id:
        qs = qs.filter(
            location_assignments__taluk_id=taluk_id,
            location_assignments__is_active=True,
        )
    if village_id:
        qs = qs.filter(
            location_assignments__village_id=village_id,
            location_assignments__is_active=True,
        )
    if search:
        normalized = normalize_search_term(search)
        if normalized:
            qs = qs.filter(
                prefix_search_q(EMPLOYEE_PROFILE_SEARCH_FIELDS, normalized)
            )
    return qs.distinct()
