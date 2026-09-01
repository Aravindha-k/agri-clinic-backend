"""Case-insensitive prefix search helpers for API querysets."""

from __future__ import annotations

from django.db.models import Q, QuerySet

# Farmer directory search (mobile + /api/v1/farmers/).
FARMER_DIRECTORY_SEARCH_FIELDS = (
    "name",
    "phone",
    "farmer_code",
    "village__name",
    "district__name",
    "taluk__name",
)

EMPLOYEE_PROFILE_SEARCH_FIELDS = (
    "employee_id",
    "user__username",
    "user__first_name",
    "user__last_name",
    "phone",
)

PROBLEM_ITEM_SEARCH_FIELDS = (
    "name",
    "tamil_name",
)

VISIT_SELECTOR_SEARCH_FIELDS = (
    "farmer_name",
    "farmer_phone",
    "notes",
    "village__name",
)

VISIT_LIST_SEARCH_FIELDS = (
    "farmer_name",
    "farmer_phone",
    "farmer__name",
    "farmer__phone",
    "employee__username",
    "employee__first_name",
    "employee__last_name",
    "employee__employee_profile__employee_id",
    "village__name",
    "crop__name_en",
    "crop__name_ta",
)

FARMER_VISIT_LIST_SEARCH_FIELDS = (
    "farmer__name",
    "farmer_name",
    "farmer__village__name",
    "field__land_name",
    "employee__username",
    "employee__employee_profile__employee_id",
    "crop__name_en",
    "crop__name_ta",
)

CROP_SEARCH_FIELDS = (
    "name_en",
    "name_ta",
    "scientific_name",
)


def normalize_search_term(value: str | None) -> str:
    """Trim search input; whitespace-only becomes empty (no filter)."""
    return (value or "").strip()


def prefix_search_q(fields: tuple[str, ...] | list[str], term: str) -> Q:
    """OR together istartswith lookups for each field."""
    combined = Q()
    for field in fields:
        combined |= Q(**{f"{field}__istartswith": term})
    return combined


def filter_queryset_by_prefix_search(
    queryset: QuerySet,
    term: str | None,
    fields: tuple[str, ...] | list[str],
) -> QuerySet:
    """Apply prefix search at queryset level (before pagination)."""
    normalized = normalize_search_term(term)
    if not normalized:
        return queryset
    return queryset.filter(prefix_search_q(fields, normalized))
