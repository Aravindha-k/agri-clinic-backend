"""
Employee location assignment service.

Operational territory is Employee ↔ Village. District/taluk on stored rows
are leftover nullable columns and are not required for new writes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from rest_framework import serializers

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.models import Village
from utils.prefix_search import (
    EMPLOYEE_PROFILE_SEARCH_FIELDS,
    prefix_search_q,
    normalize_search_term,
)


class LocationAssignmentValidationError(serializers.ValidationError):
    """Raised when assignment payload fails master validation."""


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
        EmployeeLocationAssignment.objects.filter(
            employee_id=employee_id,
            is_active=True,
            is_operational=True,
            village_id__isnull=False,
        )
        .select_related("village", "employee__user")
        .order_by("village__name")
    )


def legacy_incomplete_assignment_count(employee_id: int) -> int:
    return EmployeeLocationAssignment.objects.filter(
        employee_id=employee_id,
        is_active=True,
        is_operational=False,
    ).count()


def annotate_assignment_counts(qs: QuerySet[EmployeeProfile]) -> QuerySet[EmployeeProfile]:
    """Attach leftover district/taluk counts plus operational village counts."""
    operational = Q(
        location_assignments__is_active=True,
        location_assignments__is_operational=True,
        location_assignments__village__isnull=False,
    )
    return qs.annotate(
        location_district_count=Count(
            "location_assignments__district",
            filter=operational,
            distinct=True,
        ),
        location_taluk_count=Count(
            "location_assignments__taluk",
            filter=operational & Q(location_assignments__taluk__isnull=False),
            distinct=True,
        ),
        location_village_count=Count(
            "location_assignments__village",
            filter=operational,
            distinct=True,
        ),
    )


def _distinct_district_count(rows: list[EmployeeLocationAssignment]) -> int:
    return len({r.district_id for r in rows if r.district_id})


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
        "village_count": _distinct_village_count(rows),
        "district_count": _distinct_district_count(rows),
        "taluk_count": _distinct_taluk_count(rows),
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
    """Compact village preview for list rows — capped, counts remain authoritative."""
    villages: dict[int, dict[str, Any]] = {}

    for row in rows:
        if not row.village_id or row.village_id in villages or not row.village:
            continue
        villages[row.village_id] = {
            "id": row.village_id,
            "name": row.village.name,
            "name_ta": getattr(row.village, "name_ta", "") or "",
            "is_active": row.village.is_active,
        }

    village_list = sorted(
        villages.values(), key=lambda item: item["name"].lower()
    )[:village_limit]
    return {
        "villages": village_list,
        "districts": [],
        "taluks": [],
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
            is_operational=True,
            village_id__isnull=False,
        )
        .select_related("village")
        .order_by(
            "employee_id",
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


def village_payload_from_rows(
    rows: list[EmployeeLocationAssignment],
) -> list[dict[str, Any]]:
    villages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if not row.village_id or row.village_id in seen:
            continue
        seen.add(row.village_id)
        villages.append(
            {
                "id": row.village_id,
                "name": row.village.name,
                "name_ta": getattr(row.village, "name_ta", "") or "",
                "is_active": row.village.is_active,
            }
        )
    villages.sort(key=lambda item: item["name"].lower())
    return villages


def group_assignments_for_response(
    rows: list[EmployeeLocationAssignment],
) -> list[dict[str, Any]]:
    """Compatibility wrapper: operational assignments are a village list."""
    return village_payload_from_rows(rows)


def _coerce_int_ids(values: list[Any], *, field: str = "village_ids") -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for raw in values:
        try:
            village_id = int(raw)
        except (TypeError, ValueError):
            raise LocationAssignmentValidationError(
                {field: f"Invalid village id: {raw!r}."}
            ) from None
        if village_id not in seen:
            seen.add(village_id)
            ids.append(village_id)
    return ids


def extract_village_ids_from_payload(data: dict[str, Any]) -> list[int]:
    """
    Accept preferred {village_ids: [...]} or the legacy assignments wrapper.

    District/taluk on the wrapper are ignored. Groups without village_ids
    are rejected so district-only / taluk-only writes cannot grant territory.
    """
    if "village_ids" in data:
        ids = data.get("village_ids")
        if ids is None:
            ids = []
        if not isinstance(ids, list):
            raise LocationAssignmentValidationError(
                {"village_ids": "Must be a list of village ids."}
            )
        return _coerce_int_ids(ids)

    groups = data.get("assignments")
    if groups is None:
        raise LocationAssignmentValidationError(
            {"village_ids": "village_ids is required."}
        )
    if not isinstance(groups, list):
        raise LocationAssignmentValidationError(
            {"assignments": "Must be a list of assignment groups."}
        )
    collected: list[Any] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise LocationAssignmentValidationError(
                {f"assignments[{index}]": "Must be an object."}
            )
        village_ids = group.get("village_ids") or []
        if not village_ids:
            raise LocationAssignmentValidationError(
                {
                    f"assignments[{index}].village_ids": (
                        "village_ids are required. District-only and taluk-only "
                        "assignments are not operational."
                    )
                }
            )
        collected.extend(village_ids)
    return _coerce_int_ids(collected)


def expand_village_ids(village_ids: list[int]) -> list[Village]:
    """Validate villages exist and are active. District/Taluk are not required."""
    villages: list[Village] = []
    seen: set[int] = set()
    for village_id in village_ids:
        if village_id in seen:
            continue
        village = Village.objects.filter(pk=village_id).first()
        if not village:
            raise LocationAssignmentValidationError(
                {"village_ids": f"Village id {village_id} not found."}
            )
        if not village.is_active:
            raise LocationAssignmentValidationError(
                {
                    "village_ids": (
                        f"Village '{village.name}' is inactive and cannot be newly assigned."
                    )
                }
            )
        seen.add(village.id)
        villages.append(village)
    return villages


def expand_assignment_groups(
    assignment_groups: list[dict[str, Any]],
) -> list[Village]:
    """Compatibility wrapper around extract + expand for assignment groups."""
    village_ids = extract_village_ids_from_payload({"assignments": assignment_groups})
    return expand_village_ids(village_ids)


@transaction.atomic
def replace_employee_location_assignments(
    *,
    employee: EmployeeProfile,
    village_ids: list[int] | None = None,
    assignment_groups: list[dict[str, Any]] | None = None,
    actor: User | None = None,
) -> list[EmployeeLocationAssignment]:
    """
    Atomically replace operational assignments for an employee.

    Stored source is Employee ↔ Village. District/taluk are left null on
    new operational writes and are not derived from Village.
    """
    if village_ids is None:
        village_ids = extract_village_ids_from_payload(
            {"assignments": assignment_groups or []}
        )
    villages = expand_village_ids(village_ids)

    EmployeeLocationAssignment.objects.filter(
        employee=employee, is_operational=True
    ).delete()

    created: list[EmployeeLocationAssignment] = []
    for village in villages:
        created.append(
            EmployeeLocationAssignment.objects.create(
                employee=employee,
                village=village,
                district_id=None,
                taluk_id=None,
                is_active=True,
                is_operational=True,
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
            location_assignments__is_operational=True,
            location_assignments__village__isnull=False,
        )
    if taluk_id:
        qs = qs.filter(
            location_assignments__taluk_id=taluk_id,
            location_assignments__is_active=True,
            location_assignments__is_operational=True,
            location_assignments__village__isnull=False,
        )
    if village_id:
        qs = qs.filter(
            location_assignments__village_id=village_id,
            location_assignments__is_active=True,
            location_assignments__is_operational=True,
        )
    if search:
        normalized = normalize_search_term(search)
        if normalized:
            qs = qs.filter(
                prefix_search_q(EMPLOYEE_PROFILE_SEARCH_FIELDS, normalized)
            )
    return qs.distinct()
