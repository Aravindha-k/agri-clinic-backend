"""
Farmer vs visit data integrity audit (read-only).
Used by admin API and management commands.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from django.db import connection
from django.db.models import Count, Q

from masters.models import Farmer
from visits.models import Visit

from .helpers import e2e_test_farmer_filter

# Farmer model uses `phone` (API/clients often call it mobile).
FARMER_MOBILE_FIELD = "phone"


def _match_farmer_for_visit(visit: Visit) -> Tuple[Optional[Farmer], str]:
    """
    Try to link a visit to an existing Farmer without creating records.
    Returns (farmer, match_reason) or (None, reason).
    """
    phone = (visit.farmer_phone or "").strip()
    name = (visit.farmer_name or "").strip()

    if phone:
        matches = list(
            Farmer.objects.filter(phone=phone).order_by("id").values_list("id", flat=True)
        )
        if len(matches) == 1:
            return Farmer.objects.get(pk=matches[0]), "phone_exact"
        if len(matches) > 1:
            return None, "phone_ambiguous"

    if name and visit.village_id:
        matches = list(
            Farmer.objects.filter(name__iexact=name, village_id=visit.village_id)
            .order_by("id")
            .values_list("id", flat=True)
        )
        if len(matches) == 1:
            return Farmer.objects.get(pk=matches[0]), "name_village_exact"
        if len(matches) > 1:
            return None, "name_village_ambiguous"

    if name:
        matches = list(
            Farmer.objects.filter(name__iexact=name).order_by("id").values_list("id", flat=True)
        )
        if len(matches) == 1:
            return Farmer.objects.get(pk=matches[0]), "name_exact"
        if len(matches) > 1:
            return None, "name_ambiguous"

    return None, "no_match"


def build_farmer_visit_audit(*, orphan_limit: int = 50, farmer_limit: int = 200) -> Dict[str, Any]:
    """Aggregate counts and sample rows for admin review."""
    total_farmers_all = Farmer.objects.count()
    total_farmers_active = Farmer.objects.filter(is_active=True).count()
    total_farmers_inactive = total_farmers_all - total_farmers_active
    test_farmers_qs = Farmer.objects.filter(e2e_test_farmer_filter())
    test_farmers_total = test_farmers_qs.count()
    test_farmers_inactive = test_farmers_qs.filter(is_active=False).count()
    total_visits = Visit.objects.count()

    visits_with_farmer_fk = Visit.objects.exclude(farmer_id__isnull=True).count()
    visits_without_farmer_fk = Visit.objects.filter(farmer_id__isnull=True).count()
    distinct_farmer_ids_in_visits = (
        Visit.objects.exclude(farmer_id__isnull=True)
        .values("farmer_id")
        .distinct()
        .count()
    )

    visits_name_only = Visit.objects.filter(farmer_id__isnull=True).exclude(
        Q(farmer_name__isnull=True) | Q(farmer_name="")
    ).count()

    visits_empty_farmer = Visit.objects.filter(farmer_id__isnull=True).filter(
        Q(farmer_name__isnull=True) | Q(farmer_name="")
    ).count()

    farmers_with_visits = (
        Farmer.objects.annotate(visit_count=Count("visits", distinct=True))
        .filter(visit_count__gt=0)
        .count()
    )
    active_farmers_zero_visits = (
        Farmer.objects.filter(is_active=True)
        .annotate(visit_count=Count("visits", distinct=True))
        .filter(visit_count=0)
        .count()
    )

    farmer_rows: List[Dict[str, Any]] = list(
        Farmer.objects.annotate(visit_count=Count("visits", distinct=True))
        .order_by("-visit_count", "name")
        .values(
            "id",
            "name",
            "phone",
            "is_active",
            "visit_count",
            "village_id",
        )[:farmer_limit]
    )

    orphan_qs = (
        Visit.objects.filter(farmer_id__isnull=True)
        .select_related("village", "employee")
        .order_by("-created_at", "-id")
    )
    orphans_sample: List[Dict[str, Any]] = []
    linkable_preview: List[Dict[str, Any]] = []

    for visit in orphan_qs[:orphan_limit]:
        farmer, reason = _match_farmer_for_visit(visit)
        row = {
            "visit_id": visit.id,
            "farmer_name": visit.farmer_name,
            "farmer_phone": visit.farmer_phone,
            "village_id": visit.village_id,
            "village_name": visit.village.name if visit.village_id else None,
            "visit_date": visit.visit_date,
            "status": visit.status,
            "employee_id": visit.employee_id,
            "suggested_match": None,
            "match_reason": reason,
        }
        if farmer:
            row["suggested_match"] = {
                "id": farmer.id,
                "name": farmer.name,
                "phone": farmer.phone,
                "is_active": farmer.is_active,
            }
            if len(linkable_preview) < 20:
                linkable_preview.append(
                    {
                        "visit_id": visit.id,
                        "farmer_id": farmer.id,
                        "match_reason": reason,
                    }
                )
        orphans_sample.append(row)

    linkable_total = 0
    ambiguous_total = 0
    unmatched_total = 0
    for visit in orphan_qs.iterator(chunk_size=200):
        farmer, reason = _match_farmer_for_visit(visit)
        if farmer:
            linkable_total += 1
        elif reason.endswith("_ambiguous"):
            ambiguous_total += 1
        else:
            unmatched_total += 1

    return {
        **build_farmer_data_audit(top_n=10, duplicate_limit=50),
        "dashboard_logic": {
            "total_farmers": "Farmer.objects.count()",
            "total_visits": "Visit.objects.count()",
            "note": (
                "Dashboard farmer count is active farmers only. "
                "Visit count includes all visits, with or without farmer FK."
            ),
        },
        "farmers_page_logic": {
            "endpoint": "GET /api/v1/farmers/",
            "pagination": "page_size=20 default, max page_size=100 via page_size query param",
            "scope": "All Farmer master records (no is_active filter)",
            "visit_count": "annotated Count('visits') where visits.farmer_id is set",
            "note": (
                "List count matches dashboard total_farmers (all Farmer rows). "
                "Orphan visits (name/phone only) are not auto-linked to new Farmer rows."
            ),
        },
        "counts": {
            "total_farmers_all": total_farmers_all,
            "total_farmers_active": total_farmers_active,
            "total_farmers_inactive": total_farmers_inactive,
            "test_farmers_total": test_farmers_total,
            "test_farmers_inactive": test_farmers_inactive,
            "total_visits": total_visits,
            "visits_with_farmer_fk": visits_with_farmer_fk,
            "visits_without_farmer_fk": visits_without_farmer_fk,
            "visits_name_only_no_fk": visits_name_only,
            "visits_empty_farmer_no_fk": visits_empty_farmer,
            "distinct_farmer_id_in_visits": distinct_farmer_ids_in_visits,
            "farmers_with_at_least_one_visit": farmers_with_visits,
            "active_farmers_with_zero_visits": active_farmers_zero_visits,
        },
        "integrity": {
            "all_visits_have_valid_farmer_fk": visits_without_farmer_fk == 0,
            "orphan_visits_linkable_without_new_farmer": linkable_total,
            "orphan_visits_ambiguous_match": ambiguous_total,
            "orphan_visits_no_match": unmatched_total,
        },
        "farmers_with_visit_count": farmer_rows,
        "visits_without_farmer_fk": orphans_sample,
        "linkable_preview": linkable_preview,
    }


def _farmer_phone_uniqueness_schema() -> Dict[str, Any]:
    """Inspect Farmer.phone field and DB constraints (read-only)."""
    field = Farmer._meta.get_field(FARMER_MOBILE_FIELD)
    constraints = [
        {
            "name": getattr(c, "name", str(c)),
            "fields": list(getattr(c, "fields", ())),
            "type": c.__class__.__name__,
        }
        for c in Farmer._meta.constraints
    ]
    db_unique_indexes: List[str] = []
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = %s
                  AND indexdef ILIKE '%%UNIQUE%%'
                  AND indexdef ILIKE %s
                """,
                [Farmer._meta.db_table, f"%{FARMER_MOBILE_FIELD}%"],
            )
            db_unique_indexes = [
                {"name": row[0], "definition": row[1]} for row in cursor.fetchall()
            ]

    has_tenant_field = any(f.name == "tenant" for f in Farmer._meta.get_fields())
    tenant_mobile_constraint = any(
        getattr(c, "fields", ()) == ("tenant", FARMER_MOBILE_FIELD)
        or getattr(c, "fields", ()) == ("tenant_id", FARMER_MOBILE_FIELD)
        for c in Farmer._meta.constraints
    )

    return {
        "field_name": FARMER_MOBILE_FIELD,
        "note": "Model has no `mobile` column; audits use `Farmer.phone`.",
        "unique_on_field": bool(getattr(field, "unique", False)),
        "db_index_on_field": bool(getattr(field, "db_index", False)),
        "allows_null": bool(getattr(field, "null", False)),
        "allows_blank": bool(getattr(field, "blank", False)),
        "model_unique_constraints": constraints,
        "db_unique_indexes_on_phone": db_unique_indexes,
        "has_tenant_field": has_tenant_field,
        "has_tenant_plus_mobile_constraint": tenant_mobile_constraint,
        "uniqueness_summary": (
            "NO uniqueness on phone"
            if not getattr(field, "unique", False)
            and not db_unique_indexes
            and not tenant_mobile_constraint
            else "partial uniqueness configured — see details above"
        ),
        "suggested_production_migration": (
            None
            if has_tenant_field
            else (
                "Add tenant FK first, then:\n"
                "  models.UniqueConstraint(\n"
                '      fields=["tenant", "phone"],\n'
                '      name="unique_farmer_phone_per_tenant",\n'
                "  )\n"
                "Single-tenant app today: use UniqueConstraint(fields=['phone'], "
                'name="unique_farmer_phone") after deduplicating.'
            )
        ),
        "merge_strategy_before_constraint": [
            "1. Run: python manage.py audit_farmer_data",
            "2. For each duplicate phone group, pick canonical Farmer (most visits / oldest id).",
            "3. UPDATE visits SET farmer_id = canonical WHERE farmer_id IN (duplicate ids).",
            "4. Deactivate or merge duplicate Farmer rows manually (do not auto-delete).",
            "5. Re-run audit; apply migration only when duplicate count is 0.",
        ],
    }


def build_farmer_data_audit(
    *,
    top_n: int = 10,
    duplicate_limit: int = 50,
    zero_visit_limit: int = 50,
) -> Dict[str, Any]:
    """Full Farmer / Visit DB audit (read-only)."""
    total_farmers = Farmer.objects.count()
    total_visits = Visit.objects.count()

    distinct_farmer_ids_in_visits = (
        Visit.objects.exclude(farmer_id__isnull=True)
        .values("farmer_id")
        .distinct()
        .count()
    )

    farmers_with_phone = Farmer.objects.exclude(
        Q(phone__isnull=True) | Q(phone="")
    )
    distinct_phones = farmers_with_phone.values("phone").distinct().count()
    blank_phone_count = Farmer.objects.filter(
        Q(phone__isnull=True) | Q(phone="")
    ).count()

    duplicate_phone_groups = (
        Farmer.objects.exclude(Q(phone__isnull=True) | Q(phone=""))
        .values("phone")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
        .order_by("-cnt", "phone")
    )
    duplicate_phone_count = duplicate_phone_groups.count()

    duplicate_details: List[Dict[str, Any]] = []
    for group in duplicate_phone_groups[:duplicate_limit]:
        phone = group["phone"]
        rows = list(
            Farmer.objects.filter(phone=phone)
            .annotate(visit_count=Count("visits", distinct=True))
            .order_by("id")
            .values(
                "id",
                "name",
                "phone",
                "farmer_code",
                "is_active",
                "visit_count",
                "village_id",
                "created_at",
            )
        )
        duplicate_details.append(
            {
                "phone": phone,
                "farmer_count": group["cnt"],
                "farmers": rows,
                "merge_hint": (
                    "Keep farmer with highest visit_count; re-point visits from others."
                    if rows
                    else None
                ),
            }
        )

    visits_without_farmer = Visit.objects.filter(farmer_id__isnull=True).count()

    valid_farmer_ids = set(Farmer.objects.values_list("id", flat=True))
    visits_with_fk = Visit.objects.exclude(farmer_id__isnull=True)
    visits_broken_fk_qs = visits_with_fk.exclude(farmer_id__in=valid_farmer_ids)
    visits_broken_fk = visits_broken_fk_qs.count()
    broken_fk_sample = list(
        visits_broken_fk_qs.values("id", "farmer_id", "farmer_name", "farmer_phone")[:20]
    )

    farmers_zero_visits = (
        Farmer.objects.annotate(visit_count=Count("visits", distinct=True))
        .filter(visit_count=0)
        .order_by("id")
    )
    farmers_zero_visits_count = farmers_zero_visits.count()

    top_farmers = list(
        Farmer.objects.annotate(visit_count=Count("visits", distinct=True))
        .filter(visit_count__gt=0)
        .order_by("-visit_count", "name")
        .values("id", "name", "phone", "farmer_code", "is_active", "visit_count")[:top_n]
    )

    orphan_qs = Visit.objects.filter(farmer_id__isnull=True).order_by("-id")
    orphan_count = orphan_qs.count()

    return {
        "schema": _farmer_phone_uniqueness_schema(),
        "summary": {
            "total_farmers": total_farmers,
            "total_visits": total_visits,
            "distinct_farmer_id_in_visits": distinct_farmer_ids_in_visits,
            "distinct_phone_numbers": distinct_phones,
            "duplicate_phone_groups": duplicate_phone_count,
            "farmers_blank_phone": blank_phone_count,
            "visits_without_farmer_id": visits_without_farmer,
            "visits_broken_farmer_fk": visits_broken_fk,
            "farmers_with_zero_visits": farmers_zero_visits_count,
            "orphan_visits": orphan_count,
        },
        "duplicate_phones": duplicate_details,
        "farmers_blank_phone": list(
            Farmer.objects.filter(Q(phone__isnull=True) | Q(phone="")).values(
                "id", "name", "phone", "farmer_code", "is_active"
            )[:duplicate_limit]
        ),
        "visits_broken_farmer_fk": broken_fk_sample,
        "farmers_with_zero_visits": list(
            farmers_zero_visits.values("id", "name", "phone", "is_active")[:zero_visit_limit]
        ),
        "top_farmers_by_visits": top_farmers,
        "orphan_visits_sample": list(
            orphan_qs.values(
                "id", "farmer_name", "farmer_phone", "visit_date", "status"
            )[:20]
        ),
    }
