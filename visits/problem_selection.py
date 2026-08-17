"""Helpers for visit multi-problem selection (problem_item_ids)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from masters.location_utils import problem_allowed_for_crop
from masters.models import ProblemMaster


def normalize_problem_item_ids(raw_ids: Any) -> list[int]:
    """Deduplicate while preserving first-seen order. Reject non-int values."""
    if raw_ids in (None, ""):
        return []
    if not isinstance(raw_ids, (list, tuple)):
        raise serializers.ValidationError(
            {"problem_item_ids": "Must be a list of problem item IDs."}
        )
    seen: set[int] = set()
    ordered: list[int] = []
    for item in raw_ids:
        try:
            pk = int(item)
        except (TypeError, ValueError):
            raise serializers.ValidationError(
                {"problem_item_ids": f"Invalid problem item id: {item!r}"}
            )
        if pk in seen:
            continue
        seen.add(pk)
        ordered.append(pk)
    return ordered


def resolve_problem_items_for_visit(
    *,
    problem_item_ids: list[int] | None,
    legacy_master: ProblemMaster | None,
    crop_id: int | None,
) -> list[ProblemMaster]:
    """
    Resolve the exact set of ProblemMaster rows for a visit.

    New clients: problem_item_ids is the source of truth.
    Legacy clients: single problem_master becomes a one-item set.
    """
    if problem_item_ids is not None:
        ids = normalize_problem_item_ids(problem_item_ids)
        if not ids:
            return []
        found = list(
            ProblemMaster.objects.filter(pk__in=ids, is_active=True).select_related(
                "category"
            )
        )
        by_id = {p.pk: p for p in found}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise serializers.ValidationError(
                {
                    "problem_item_ids": (
                        f"Unknown or inactive problem item id(s): {missing}"
                    )
                }
            )
        ordered = [by_id[i] for i in ids]
        bad = [p for p in ordered if not problem_allowed_for_crop(p, crop_id)]
        if bad and crop_id:
            names = ", ".join(p.name for p in bad)
            raise serializers.ValidationError(
                {
                    "problem_item_ids": (
                        f"Problem(s) not allowed for the selected crop: {names}"
                    )
                }
            )
        return ordered

    if legacy_master is not None:
        if not legacy_master.is_active:
            raise serializers.ValidationError(
                {"problem_master": "Inactive problem cannot be assigned."}
            )
        if crop_id and not problem_allowed_for_crop(legacy_master, crop_id):
            raise serializers.ValidationError(
                {
                    "problem_master": (
                        "Problem subcategory is not available for the selected crop."
                    )
                }
            )
        return [legacy_master]
    return []


def apply_problem_items_to_visit(visit, problems: list[ProblemMaster]) -> None:
    """Set M2M exact set and mirror first item into legacy FK fields."""
    visit.problem_items.set(problems)
    if problems:
        first = problems[0]
        visit.problem_master = first
        visit.problem_category = first.category
        visit.save(update_fields=["problem_master", "problem_category", "updated_at"])
    else:
        # Leave legacy nullable fields alone unless caller cleared them.
        pass


def serialize_visit_problems(visit) -> list[dict]:
    items = list(
        visit.problem_items.filter(is_active=True)
        .select_related("category")
        .order_by("category__name", "name")
    )
    if not items and visit.problem_master_id:
        master = visit.problem_master
        if master is not None:
            items = [master]
    rows = []
    for item in items:
        cat = item.category
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "tamil_name": item.tamil_name or "",
                "category": {
                    "id": cat.id if cat else None,
                    "name": cat.name if cat else "",
                    "code": cat.code if cat else "",
                },
            }
        )
    return rows
