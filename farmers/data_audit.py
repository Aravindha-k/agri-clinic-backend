"""
Shared audit/cleanup helpers for farmer and visit test data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db.models import Count, Q

from farmers.helpers import e2e_test_farmer_filter, is_e2e_test_farmer
from visits.submitted import (
    get_visit_cleanup_counts,
    incomplete_visit_filter,
    incomplete_visits_qs,
    submitted_visit_filter,
    submitted_visits_qs,
)

TEST_NAME_TOKENS = ("demo", "dummy", "sample", "e2e", "test farmer", "smoke")


def test_farmer_filter() -> Q:
    """Farmers that look like automated/demo records (audit; not all are safe to delete)."""
    q = e2e_test_farmer_filter()
    for token in TEST_NAME_TOKENS:
        q |= Q(name__icontains=token)
    q |= Q(name__istartswith="Test ")
    q |= Q(name__iexact="Test")
    return q


def is_clearly_test_farmer(farmer: Any) -> bool:
    """Conservative delete guard — only obvious test/demo rows."""
    if is_e2e_test_farmer(farmer):
        return True
    name = (getattr(farmer, "name", None) or "").strip().lower()
    if name.startswith("test ") or name in ("test", "demo farmer", "dummy farmer"):
        return True
    return any(token in name for token in TEST_NAME_TOKENS)


def draft_status_visit_filter() -> Q:
    """Legacy workflow rows that were never fully submitted."""
    return Q(status__in=("pending", "active")) & ~submitted_visit_filter()


def cleanup_visits_qs():
    """Visits safe to remove: incomplete and/or legacy draft status."""
    from visits.models import Visit

    return Visit.objects.filter(incomplete_visit_filter() | draft_status_visit_filter())


def test_farmers_qs():
    from masters.models import Farmer

    return Farmer.objects.filter(test_farmer_filter())


def farmers_safe_to_delete():
    """
    Test farmers with no submitted visits (visits will be removed separately first).
    """
    from masters.models import Farmer

    qs = Farmer.objects.filter(test_farmer_filter())
    safe = []
    skipped = []
    for farmer in qs.iterator():
        if not is_clearly_test_farmer(farmer):
            skipped.append((farmer, "name pattern not clearly test"))
            continue
        if submitted_visits_qs().filter(farmer_id=farmer.pk).exists():
            skipped.append((farmer, "has submitted visit(s)"))
            continue
        safe.append(farmer)
    return safe, skipped


def duplicate_farmers_by_phone(limit: int = 20) -> list[dict]:
    from masters.models import Farmer

    dupes = (
        Farmer.objects.exclude(phone__isnull=True)
        .exclude(phone="")
        .values("phone")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
        .order_by("-c")[:limit]
    )
    out = []
    for row in dupes:
        farmers = list(
            Farmer.objects.filter(phone=row["phone"]).values(
                "id", "name", "phone", "is_active"
            )
        )
        out.append({"phone": row["phone"], "count": row["c"], "farmers": farmers})
    return out


def duplicate_visits_by_slot(limit: int = 20) -> list[dict]:
    from visits.models import Visit

    dupes = (
        Visit.objects.filter(
            farmer_id__isnull=False,
            visit_date__isnull=False,
        )
        .values("farmer_id", "employee_id", "visit_date", "visit_time")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
        .order_by("-c")[:limit]
    )
    out = []
    for row in dupes:
        visits = list(
            Visit.objects.filter(
                farmer_id=row["farmer_id"],
                employee_id=row["employee_id"],
                visit_date=row["visit_date"],
                visit_time=row["visit_time"],
            ).values("id", "status", "crop_id", "latitude", "longitude")
        )
        out.append({**row, "visit_ids": [v["id"] for v in visits], "visits": visits})
    return out


def submitted_visits_by_farmer(limit: int = 50) -> list[dict]:
    from masters.models import Farmer

    rows = list(
        submitted_visits_qs()
        .values("farmer_id", "farmer__name")
        .annotate(visit_count=Count("id"))
        .order_by("-visit_count", "farmer__name")[:limit]
    )
    for row in rows:
        if row["farmer_id"] and not row.get("farmer__name"):
            row["farmer__name"] = (
                Farmer.objects.filter(pk=row["farmer_id"])
                .values_list("name", flat=True)
                .first()
            )
    return rows


def submitted_visits_by_employee(limit: int = 50) -> list[dict]:
    return list(
        submitted_visits_qs()
        .values("employee_id", "employee__username")
        .annotate(visit_count=Count("id"))
        .order_by("-visit_count", "employee__username")[:limit]
    )


def build_agri_audit_report() -> dict:
    from masters.models import Farmer
    from visits.models import Visit

    visit_counts = get_visit_cleanup_counts()
    status_breakdown = list(
        Visit.objects.values("status")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    farmers_total = Farmer.objects.count()
    farmers_active = Farmer.objects.filter(is_active=True).count()
    farmers_inactive = farmers_total - farmers_active
    test_farmers = test_farmers_qs().count()
    clearly_test = sum(1 for f in test_farmers_qs().iterator() if is_clearly_test_farmer(f))

    return {
        "farmers": {
            "total": farmers_total,
            "active": farmers_active,
            "inactive": farmers_inactive,
            "test_pattern_matches": test_farmers,
            "clearly_test": clearly_test,
        },
        "visits": visit_counts,
        "visits_by_status": status_breakdown,
        "cleanup_candidates": {
            "visits_to_remove": cleanup_visits_qs().count(),
            "incomplete": incomplete_visits_qs().count(),
            "draft_status_incomplete": Visit.objects.filter(
                draft_status_visit_filter()
            ).count(),
            "orphan_no_farmer": Visit.objects.filter(farmer_id__isnull=True).count(),
        },
        "duplicate_farmers_by_phone": duplicate_farmers_by_phone(),
        "duplicate_visits_by_slot": duplicate_visits_by_slot(),
        "submitted_by_farmer": submitted_visits_by_farmer(),
        "submitted_by_employee": submitted_visits_by_employee(),
    }
