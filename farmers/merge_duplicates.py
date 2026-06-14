"""
Safe farmer duplicate merge (used by merge_farmer_duplicates management command).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from django.db import transaction
from django.db.models import Count

from masters.models import CropIssue, Farmer, FarmerActivity, FarmerField, FieldCrop
from visits.models import Visit

from .duplicate_audit import build_farmer_duplicate_audit, parse_quarter_keys


def _merge_source_fields(primary: Farmer, duplicate: Farmer) -> None:
    quarters: Set[str] = parse_quarter_keys(primary.source_quarter)
    quarters |= parse_quarter_keys(duplicate.source_quarter)
    if quarters:
        primary.source_quarter = ",".join(sorted(quarters))

    files = [f.strip() for f in (primary.source_file, duplicate.source_file) if f and f.strip()]
    if files:
        primary.source_file = ";".join(dict.fromkeys(files))


def _move_farmer_relations(primary_id: int, duplicate_id: int) -> Dict[str, int]:
    moved = {
        "visits": 0,
        "farmer_activities": 0,
        "farmer_fields": 0,
        "field_crops": 0,
        "issues_via_visits": 0,
    }

    moved["visits"] = Visit.objects.filter(farmer_id=duplicate_id).update(farmer_id=primary_id)
    moved["farmer_activities"] = FarmerActivity.objects.filter(farmer_id=duplicate_id).update(
        farmer_id=primary_id
    )

    field_ids = list(
        FarmerField.objects.filter(farmer_id=duplicate_id).values_list("id", flat=True)
    )
    if field_ids:
        moved["farmer_fields"] = FarmerField.objects.filter(id__in=field_ids).update(
            farmer_id=primary_id
        )
        moved["field_crops"] = FieldCrop.objects.filter(land_id__in=field_ids).count()

    visit_ids = list(Visit.objects.filter(farmer_id=primary_id).values_list("id", flat=True))
    if visit_ids:
        moved["issues_via_visits"] = CropIssue.objects.filter(visit_id__in=visit_ids).count()

    return moved


def _plan_from_audit(audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One merge plan per safe group; dedupe by duplicate id."""
    plans: List[Dict[str, Any]] = []
    claimed_duplicate_ids: Set[int] = set()

    for group in audit.get("safe_merge_groups", []):
        farmers = group.get("farmers") or []
        if len(farmers) < 2:
            continue
        primary_id = min(f["id"] for f in farmers)
        for row in farmers:
            dup_id = row["id"]
            if dup_id == primary_id or dup_id in claimed_duplicate_ids:
                continue
            claimed_duplicate_ids.add(dup_id)
            plans.append(
                {
                    "primary_id": primary_id,
                    "duplicate_id": dup_id,
                    "reason": group.get("phone")
                    and f"phone={group['phone']}"
                    or f"name_village={group.get('normalized_name')}",
                    "classification": "safe",
                }
            )
    return plans


def preview_merge(*, group_limit: int = 50) -> Dict[str, Any]:
    audit = build_farmer_duplicate_audit(group_limit=group_limit)
    plans = _plan_from_audit(audit)
    return {
        "audit_summary": audit["summary"],
        "merge_plans": plans,
        "would_delete": len(plans),
        "ambiguous_skipped": audit["summary"]["unsafe_ambiguous_duplicates"],
    }


@transaction.atomic
def execute_merge(*, group_limit: int = 50) -> Dict[str, Any]:
    preview = preview_merge(group_limit=group_limit)
    plans = preview["merge_plans"]
    results: List[Dict[str, Any]] = []

    for plan in plans:
        primary = Farmer.objects.select_for_update().get(pk=plan["primary_id"])
        duplicate = Farmer.objects.select_for_update().get(pk=plan["duplicate_id"])
        moved = _move_farmer_relations(primary.id, duplicate.id)
        _merge_source_fields(primary, duplicate)
        primary.save(update_fields=["source_quarter", "source_file", "updated_at"])
        duplicate.delete()
        results.append({**plan, "moved": moved})

    post_audit = build_farmer_duplicate_audit(group_limit=group_limit)
    return {
        "merged": len(results),
        "results": results,
        "post_audit_summary": post_audit["summary"],
    }
