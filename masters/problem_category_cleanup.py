"""Audit and soft-deactivate unused problem categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db.models import Count

from masters.models import ProblemCategory, ProblemMaster
from masters.problem_item_utils import problem_categories_with_active_items

# Categories seeded for field visits / Excel import (client master data).
CLIENT_CATEGORY_CODES = frozenset(
    {
        ProblemCategory.CODE_PEST,
        ProblemCategory.CODE_DISEASE,
        ProblemCategory.CODE_NUTRIENT,
        ProblemCategory.CODE_OTHERS,
    }
)


def audit_problem_categories() -> dict[str, Any]:
    """Read-only audit of categories vs active problem items."""
    all_categories = list(
        ProblemCategory.objects.all()
        .order_by("id")
        .values("id", "name", "code", "is_active", "requires_problem_master")
    )

    counts_by_category = list(
        ProblemMaster.objects.filter(is_active=True)
        .values("category_id", "category__name", "category__code")
        .annotate(active_item_count=Count("id"))
        .order_by("category__code")
    )

    used_category_ids = {
        row["category_id"] for row in counts_by_category if row["active_item_count"] > 0
    }
    zero_item_categories = [
        row
        for row in all_categories
        if row["id"] not in used_category_ids
    ]

    client_import_categories = [
        row
        for row in counts_by_category
        if row["category__code"] in CLIENT_CATEGORY_CODES
        and row["active_item_count"] > 0
    ]

    categories_to_keep = [
        row for row in all_categories if row["id"] in used_category_ids
    ]
    categories_to_deactivate = [
        row
        for row in all_categories
        if row["id"] not in used_category_ids and row["is_active"]
    ]

    return {
        "all_categories": all_categories,
        "counts_by_category": counts_by_category,
        "zero_item_categories": zero_item_categories,
        "client_import_categories": client_import_categories,
        "categories_to_keep": categories_to_keep,
        "categories_to_deactivate": categories_to_deactivate,
        "total_active_problem_items": ProblemMaster.objects.filter(
            is_active=True
        ).count(),
    }


@dataclass
class CategoryCleanupResult:
    deactivated: list[dict[str, Any]] = field(default_factory=list)
    already_inactive: list[dict[str, Any]] = field(default_factory=list)
    kept: list[dict[str, Any]] = field(default_factory=list)

    @property
    def deactivated_count(self) -> int:
        return len(self.deactivated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deactivated": self.deactivated,
            "already_inactive": self.already_inactive,
            "kept": self.kept,
            "deactivated_count": len(self.deactivated),
        }


def deactivate_unused_problem_categories(*, dry_run: bool = True) -> CategoryCleanupResult:
    """
    Soft-deactivate categories with zero active problem items.
    Never hard-deletes (ProblemMaster FK uses PROTECT).
    """
    audit = audit_problem_categories()
    result = CategoryCleanupResult()
    result.kept = audit["categories_to_keep"]

    for row in audit["zero_item_categories"]:
        if not row["is_active"]:
            result.already_inactive.append(row)
            continue
        if not dry_run:
            ProblemCategory.objects.filter(pk=row["id"]).update(is_active=False)
        result.deactivated.append(row)

    return result
