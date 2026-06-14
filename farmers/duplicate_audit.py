"""
Read-only duplicate farmer audit after quarter imports.

Checks phone duplicates, normalized name + village duplicates, and cross-quarter overlap.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from django.db.models import Count, Q

from masters.models import Farmer

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_farmer_name(name: Optional[str]) -> str:
    """lower case, trim, remove dots, collapse duplicate spaces."""
    if not name:
        return ""
    s = name.lower().strip().replace(".", "")
    return _WHITESPACE_RE.sub(" ", s)


def parse_quarter_keys(source_quarter: Optional[str]) -> Set[str]:
    if not source_quarter:
        return set()
    return {q.strip() for q in source_quarter.split(",") if q.strip()}


def _farmer_row(f: Farmer) -> Dict[str, Any]:
    return {
        "id": f.id,
        "name": f.name,
        "normalized_name": normalize_farmer_name(f.name),
        "phone": (f.phone or "").strip(),
        "village_id": f.village_id,
        "source_quarter": f.source_quarter or "",
        "source_file": f.source_file or "",
        "is_active": f.is_active,
        "created_at": f.created_at,
        "farmer_code": f.farmer_code,
    }


def _classify_phone_group(rows: List[Dict[str, Any]]) -> str:
    """safe | ambiguous"""
    villages = {r["village_id"] for r in rows}
    norm_names = {r["normalized_name"] for r in rows if r["normalized_name"]}
    if len(villages) > 1:
        return "ambiguous"
    if len(norm_names) > 1:
        return "ambiguous"
    return "safe"


def _classify_name_village_group(rows: List[Dict[str, Any]]) -> str:
    """safe | ambiguous — no-phone groups only."""
    phones = {r["phone"] for r in rows if r["phone"]}
    if phones:
        return "ambiguous"
    return "safe"


def build_farmer_duplicate_audit(*, group_limit: int = 50) -> Dict[str, Any]:
    farmers = list(
        Farmer.objects.select_related("village").order_by("id")
    )
    total = len(farmers)
    active = sum(1 for f in farmers if f.is_active)

    phone_groups_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    nv_groups_map: Dict[Tuple[str, Optional[int]], List[Dict[str, Any]]] = defaultdict(list)

    for farmer in farmers:
        row = _farmer_row(farmer)
        phone = row["phone"]
        if phone:
            phone_groups_map[phone].append(row)
        norm = row["normalized_name"]
        if norm:
            nv_groups_map[(norm, row["village_id"])].append(row)

    phone_duplicate_groups: List[Dict[str, Any]] = []
    safe_phone_groups: List[Dict[str, Any]] = []
    ambiguous_phone_groups: List[Dict[str, Any]] = []

    for phone, rows in sorted(phone_groups_map.items(), key=lambda x: (-len(x[1]), x[0])):
        if len(rows) < 2:
            continue
        classification = _classify_phone_group(rows)
        group = {
            "phone": phone,
            "farmer_count": len(rows),
            "classification": classification,
            "farmers": rows,
            "primary_id": min(r["id"] for r in rows),
        }
        phone_duplicate_groups.append(group)
        if classification == "safe":
            safe_phone_groups.append(group)
        else:
            ambiguous_phone_groups.append(group)

    nv_duplicate_groups: List[Dict[str, Any]] = []
    safe_nv_groups: List[Dict[str, Any]] = []
    ambiguous_nv_groups: List[Dict[str, Any]] = []

    for (norm_name, village_id), rows in sorted(
        nv_groups_map.items(), key=lambda x: (-len(x[1]), x[0][0])
    ):
        if len(rows) < 2:
            continue
        classification = _classify_name_village_group(rows)
        group = {
            "normalized_name": norm_name,
            "village_id": village_id,
            "farmer_count": len(rows),
            "classification": classification,
            "farmers": rows,
            "primary_id": min(r["id"] for r in rows),
        }
        nv_duplicate_groups.append(group)
        if classification == "safe":
            safe_nv_groups.append(group)
        else:
            ambiguous_nv_groups.append(group)

    cross_quarter_groups: List[Dict[str, Any]] = []
    for group in phone_duplicate_groups + nv_duplicate_groups:
        all_quarters: Set[str] = set()
        for row in group["farmers"]:
            all_quarters |= parse_quarter_keys(row["source_quarter"])
        if len(all_quarters) > 1:
            cross_quarter_groups.append(
                {
                    **{k: v for k, v in group.items() if k != "farmers"},
                    "quarters": sorted(all_quarters),
                    "farmer_ids": [r["id"] for r in group["farmers"]],
                }
            )

    likely_duplicate_records = sum(
        len(g["farmers"]) - 1
        for g in phone_duplicate_groups + nv_duplicate_groups
        if g["classification"] == "safe"
    )
    safe_merge_candidates = len(safe_phone_groups) + len(safe_nv_groups)
    unsafe_merge_candidates = len(ambiguous_phone_groups) + len(ambiguous_nv_groups)

    distinct_phones = (
        Farmer.objects.exclude(Q(phone__isnull=True) | Q(phone=""))
        .values("phone")
        .distinct()
        .count()
    )
    blank_phone = Farmer.objects.filter(Q(phone__isnull=True) | Q(phone="")).count()

    quarter_dist: Dict[str, int] = defaultdict(int)
    for farmer in farmers:
        keys = parse_quarter_keys(farmer.source_quarter)
        if not keys:
            quarter_dist["(blank)"] += 1
        else:
            for key in keys:
                quarter_dist[key] += 1

    return {
        "summary": {
            "total_farmers": total,
            "active_farmers": active,
            "inactive_farmers": total - active,
            "distinct_phone_numbers": distinct_phones,
            "farmers_blank_phone": blank_phone,
            "duplicate_phone_groups": len(phone_duplicate_groups),
            "duplicate_name_village_groups": len(nv_duplicate_groups),
            "likely_duplicate_records": likely_duplicate_records,
            "safe_merge_candidates": safe_merge_candidates,
            "unsafe_ambiguous_duplicates": unsafe_merge_candidates,
            "cross_quarter_duplicate_groups": len(cross_quarter_groups),
            "dashboard_count_note": (
                "Dashboard uses active_farmers_queryset().count(); "
                "all Farmer rows when every record is active."
            ),
        },
        "quarter_distribution": dict(sorted(quarter_dist.items())),
        "duplicate_phones": phone_duplicate_groups[:group_limit],
        "duplicate_name_village": nv_duplicate_groups[:group_limit],
        "safe_merge_groups": (safe_phone_groups + safe_nv_groups)[:group_limit],
        "ambiguous_groups": (ambiguous_phone_groups + ambiguous_nv_groups)[:group_limit],
        "cross_quarter_groups": cross_quarter_groups[:group_limit],
    }
