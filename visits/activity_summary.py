"""
Admin Field Visits management activity summary (ORM aggregates).

Roster starts from eligible field employees (not Visit rows) so zero-visit
employees appear. Visit metrics reuse submitted_visits_qs + Asia/Kolkata
visit_date semantics and the reports gps_compliant lat/lng rule.

Supports inclusive ranges via start_date/end_date. Single-day callers may
still pass the same date for both bounds.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Max, Q

from accounts.location_assignments import field_employee_queryset
from reports.summary import _display_employee_name
from visits.date_filters import apply_visit_date_range
from visits.submitted import submitted_visits_qs


def eligible_field_employee_roster():
    """
    Employees legitimately eligible for field-visit activity.

    Reuses field_employee_queryset (excludes staff) plus the same active
    flags as field_employee_may_authenticate: User.is_active,
    is_active_employee, can_login, and not superuser.
    """
    return (
        field_employee_queryset()
        .filter(
            user__is_superuser=False,
            user__is_active=True,
            is_active_employee=True,
            can_login=True,
        )
        .select_related("user")
    )


def build_visit_activity_summary(*, start_date: date, end_date: date) -> dict:
    """
    Activity summary for an inclusive Asia/Kolkata visit-date range.

    Definitions:
      - submitted visit: visits.submitted.submitted_visits_qs (same as Admin list)
      - date range: apply_visit_date_range on visit_date
        (created_at local date fallback when visit_date is null)
      - gps_verified: non-null latitude AND longitude (reports gps_compliant)
      - latest_visit_at: Max(Visit.created_at) for that employee within range
        (no submitted_at on Visit; Admin list also orders by -created_at)
      - user_id: AUTH_USER_MODEL pk (Visit.employee_id), never EmployeeProfile.pk

    Returns metric keys only (no date / start_date / end_date). Callers attach
    the appropriate date contract for ?date= vs ?start_date=&end_date=.
    """
    roster = list(
        eligible_field_employee_roster().values(
            "user_id",
            "employee_id",
            "user__username",
            "user__first_name",
            "user__last_name",
        )
    )
    user_ids = [row["user_id"] for row in roster]

    range_qs = apply_visit_date_range(
        submitted_visits_qs().filter(employee_id__in=user_ids),
        start=start_date,
        end=end_date,
    )

    per_employee = {
        row["employee_id"]: row
        for row in range_qs.values("employee_id").annotate(
            visit_count=Count("id"),
            latest_visit_at=Max("created_at"),
        )
    }

    totals = range_qs.aggregate(
        total_visits=Count("id"),
        gps_verified=Count(
            "id",
            filter=Q(latitude__isnull=False, longitude__isnull=False),
        ),
    )

    employees = []
    for row in roster:
        stats = per_employee.get(row["user_id"])
        visit_count = int(stats["visit_count"]) if stats else 0
        employees.append(
            {
                "user_id": row["user_id"],
                "employee_id": row["employee_id"],
                "name": _display_employee_name(
                    row["user__username"],
                    row["user__first_name"],
                    row["user__last_name"],
                ),
                "visit_count": visit_count,
                "latest_visit_at": stats["latest_visit_at"] if stats else None,
            }
        )

    employees.sort(
        key=lambda e: (
            -e["visit_count"],
            (e["name"] or "").casefold(),
            (e["employee_id"] or "").casefold(),
        )
    )

    active_staff = sum(1 for e in employees if e["visit_count"] >= 1)
    eligible_count = len(employees)

    return {
        "total_visits": int(totals["total_visits"] or 0),
        "active_staff": active_staff,
        "no_visits": eligible_count - active_staff,
        "gps_verified": int(totals["gps_verified"] or 0),
        "employees": employees,
    }
