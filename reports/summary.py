"""Admin report summary aggregates (ORM-level, no raw visit dump)."""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import Coalesce, TruncDate

from accounts.models import EmployeeProfile
from visits.date_filters import apply_visit_date_range
from visits.models import Visit, VisitAttachment, VisitMedia
from visits.submitted import submitted_visits_qs


def _display_employee_name(username, first_name, last_name) -> str:
    full = " ".join(p for p in (first_name or "", last_name or "") if p).strip()
    return full or username or "Unknown"


def _resolve_employee_filter(raw):
    """Accept user pk or employee_id code. None means no filter."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.isdigit():
        return Q(employee_id=int(value))
    profile = (
        EmployeeProfile.objects.filter(employee_id__iexact=value)
        .only("user_id")
        .first()
    )
    if profile:
        return Q(employee_id=profile.user_id)
    return Q(pk__in=[])  # unknown employee → empty result


def filtered_submitted_visits(
    *,
    start: date | None = None,
    end: date | None = None,
    employee=None,
    district=None,
):
    qs = submitted_visits_qs(Visit.objects.all())
    qs = apply_visit_date_range(qs, start, end)

    emp_q = _resolve_employee_filter(employee)
    if emp_q is not None:
        qs = qs.filter(emp_q)

    if district is not None and str(district).strip():
        d = str(district).strip()
        if d.isdigit():
            qs = qs.filter(district_id=int(d))
        else:
            qs = qs.filter(district__name__iexact=d)

    return qs.select_related(
        "employee",
        "employee__employee_profile",
        "district",
        "village",
        "crop",
        "farmer",
    )


def build_admin_report_summary(
    *,
    start: date | None = None,
    end: date | None = None,
    employee=None,
    district=None,
) -> dict:
    qs = filtered_submitted_visits(
        start=start, end=end, employee=employee, district=district
    )

    has_media = VisitMedia.objects.filter(visit_id=OuterRef("pk"))
    has_att = VisitAttachment.objects.filter(visit_id=OuterRef("pk"))
    qs = qs.annotate(_has_evidence=Exists(has_media) | Exists(has_att))

    totals_row = qs.aggregate(
        visits=Count("id"),
        farmers=Count("farmer_id", distinct=True),
        employees=Count("employee_id", distinct=True),
        gps_compliant=Count(
            "id",
            filter=Q(latitude__isnull=False, longitude__isnull=False),
        ),
        visits_with_evidence=Count("id", filter=Q(_has_evidence=True)),
    )

    visit_ids = qs.values_list("id", flat=True)
    media_files = VisitMedia.objects.filter(visit_id__in=visit_ids).count()
    attachment_files = VisitAttachment.objects.filter(visit_id__in=visit_ids).count()

    visits_by_day = [
        {
            "date": row["day"].isoformat() if row["day"] else None,
            "count": row["count"],
        }
        for row in (
            qs.annotate(day=Coalesce("visit_date", TruncDate("created_at")))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        if row["day"] is not None
    ]

    visits_by_employee = [
        {
            "employee_id": row["employee_id"],
            "employee_code": row["employee__employee_profile__employee_id"],
            "employee_name": _display_employee_name(
                row["employee__username"],
                row["employee__first_name"],
                row["employee__last_name"],
            ),
            "count": row["count"],
        }
        for row in (
            qs.values(
                "employee_id",
                "employee__username",
                "employee__first_name",
                "employee__last_name",
                "employee__employee_profile__employee_id",
            )
            .annotate(count=Count("id"))
            .order_by("-count")[:50]
        )
    ]

    visits_by_district = [
        {
            "district_id": row["district_id"],
            "district_name": row["district__name"] or "—",
            "count": row["count"],
        }
        for row in (
            qs.values("district_id", "district__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:50]
        )
    ]

    visits_by_crop = [
        {
            "crop_id": row["crop_id"],
            "crop_name": row["crop__name_en"] or "—",
            "count": row["count"],
        }
        for row in (
            qs.values("crop_id", "crop__name_en")
            .annotate(count=Count("id"))
            .order_by("-count")[:50]
        )
    ]

    villages_covered = (
        qs.exclude(village_id=None).values("village_id").distinct().count()
    )
    farmer_coverage_by_village = [
        {
            "village_id": row["village_id"],
            "village_name": row["village__name"] or "—",
            "farmers": row["farmers"],
        }
        for row in (
            qs.exclude(Q(village_id=None) | Q(farmer_id=None))
            .values("village_id", "village__name")
            .annotate(farmers=Count("farmer_id", distinct=True))
            .order_by("-farmers")[:20]
        )
    ]

    visits = totals_row["visits"] or 0
    gps_compliant = totals_row["gps_compliant"] or 0
    with_evidence = totals_row["visits_with_evidence"] or 0
    evidence_files = media_files + attachment_files

    return {
        "period": {
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
        },
        "totals": {
            "visits": visits,
            "submitted_visits": visits,
            "employees": totals_row["employees"] or 0,
            "farmers": totals_row["farmers"] or 0,
            "villages_covered": villages_covered,
            "gps_compliant": gps_compliant,
            "gps_compliance_pct": round((gps_compliant / visits) * 100) if visits else 0,
            "visits_with_evidence": with_evidence,
            "evidence_files": evidence_files,
            "evidence_rate_pct": round((with_evidence / visits) * 100) if visits else 0,
        },
        "visits_by_day": visits_by_day,
        "visits_by_employee": visits_by_employee,
        "visits_by_district": visits_by_district,
        "visits_by_crop": visits_by_crop,
        "farmer_coverage_by_village": farmer_coverage_by_village,
    }
