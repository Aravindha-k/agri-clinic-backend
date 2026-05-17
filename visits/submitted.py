"""
Visit records are "submitted" when required field-visit details exist.
Workflow does not use Visit.status in API logic.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from rest_framework import serializers

from visits.models import Visit

SUBMIT_VISIT_REQUIRED_MESSAGE = (
    "Farmer, crop, and GPS location are required to submit a visit."
)


def submitted_visit_filter() -> Q:
    """Minimum details after employee submit (matches mobile validation)."""
    return Q(
        farmer_id__isnull=False,
        crop_id__isnull=False,
        latitude__isnull=False,
        longitude__isnull=False,
    )


def visit_has_submitted_details(visit: Visit) -> bool:
    return bool(
        visit.farmer_id
        and visit.crop_id
        and visit.latitude is not None
        and visit.longitude is not None
    )


def visit_data_has_submit_fields(data: dict) -> bool:
    """True when payload has farmer, crop, and GPS (after FK resolution)."""
    farmer = data.get("farmer")
    farmer_id = getattr(farmer, "pk", farmer)
    crop = data.get("crop")
    crop_id = getattr(crop, "pk", crop)
    return bool(
        farmer_id
        and crop_id
        and data.get("latitude") is not None
        and data.get("longitude") is not None
    )


def validate_visit_submit_data(data: dict) -> None:
    """Raise ValidationError before any Visit row is inserted."""
    if not visit_data_has_submit_fields(data):
        raise serializers.ValidationError(SUBMIT_VISIT_REQUIRED_MESSAGE)


def submitted_visits_qs(base: QuerySet | None = None) -> QuerySet:
    qs = base if base is not None else Visit.objects.all()
    return qs.filter(submitted_visit_filter())


def incomplete_visit_filter() -> Q:
    """Inverse of submitted_visit_filter — safe to delete as legacy rows."""
    return (
        Q(farmer_id__isnull=True)
        | Q(crop_id__isnull=True)
        | Q(latitude__isnull=True)
        | Q(longitude__isnull=True)
    )


def incomplete_visits_qs(base: QuerySet | None = None) -> QuerySet:
    qs = base if base is not None else Visit.objects.all()
    return qs.filter(incomplete_visit_filter())


def get_visit_cleanup_counts(base: QuerySet | None = None) -> dict:
    """Counts for clean_incomplete_visits / audits (breakdown rows may overlap)."""
    from django.db.models import Count

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
