"""
Visit submit / submitted queryset helpers.

Canonical implementation lives in visits.field_visit (field visit + legacy GPS).
"""

from django.db.models import Q

from visits.field_visit import (  # noqa: F401
    FIELD_VISIT_REQUIRED_MESSAGE,
    LEGACY_SUBMIT_REQUIRED_MESSAGE,
    SUBMIT_VISIT_REQUIRED_MESSAGE,
    incomplete_visit_filter,
    incomplete_visits_qs,
    submitted_visit_filter,
    submitted_visits_qs,
    validate_field_visit_submit_data,
    validate_visit_submit_data,
    visit_data_has_field_visit_fields,
    visit_data_has_legacy_submit_fields,
    visit_has_field_visit_details,
    visit_has_legacy_submit_details,
    visit_has_submitted_details,
)


def visit_data_has_submit_fields(data: dict) -> bool:
    """Backward-compatible alias."""
    return visit_data_has_legacy_submit_fields(data) or visit_data_has_field_visit_fields(
        data
    )


def get_visit_cleanup_counts(base=None) -> dict:
    """Counts for clean_incomplete_visits / audits."""
    from django.db.models import Count

    from visits.models import Visit

    qs = base if base is not None else Visit.objects.all()
    total = qs.count()
    submitted_qs = submitted_visits_qs(qs)
    submitted = submitted_qs.count()
    by_employee = list(
        submitted_qs.values("employee_id", "employee__username")
        .annotate(visit_count=Count("id"))
        .order_by("-visit_count", "employee__username")
    )
    return {
        "total_visits": total,
        "submitted_visits": submitted,
        "incomplete_visits": incomplete_visits_qs(qs).count(),
        "no_farmer": qs.filter(farmer_id__isnull=True).count(),
        "missing_crop": qs.filter(crop_id__isnull=True).count(),
        "missing_gps": qs.filter(
            Q(latitude__isnull=True) | Q(longitude__isnull=True)
        ).count(),
        "submitted_by_employee": [
            {
                "employee_id": row["employee_id"],
                "employee_username": row["employee__username"] or "",
                "visit_count": row["visit_count"],
            }
            for row in by_employee
        ],
    }

