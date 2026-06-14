"""Mobile dashboard KPI helpers (visits, coverage, tracking)."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.utils import timezone

from tracking.location_helpers import workday_distance_km
from tracking.models import LocationLog, WorkDay
from visits.farmer_visit_summary import count_farmers_covered_today
from visits.submitted import submitted_visits_qs


def mobile_dashboard_metrics(user: User) -> dict:
    today = timezone.localdate()
    visit_qs = submitted_visits_qs().filter(employee=user)
    today_visits = visit_qs.filter(visit_date=today).count()
    total_visits = visit_qs.count()
    farmers_covered = count_farmers_covered_today(user, today=today)

    workday = (
        WorkDay.objects.filter(user=user, date=today)
        .order_by("-is_active", "-start_time")
        .first()
    )
    distance_today_km = 0.0
    route_points_today = 0
    workday_id = None
    work_status = "not_started"

    if workday:
        workday_id = workday.id
        distance_today_km = workday_distance_km(workday.pk)
        route_points_today = LocationLog.objects.filter(workday=workday).count()
        if workday.is_active:
            work_status = "started"
        elif workday.auto_ended:
            work_status = "expired"
        else:
            work_status = "stopped"
    elif WorkDay.objects.filter(user=user, auto_ended=True).exists():
        work_status = "expired"

    return {
        "visits_today": today_visits,
        "today_visits": today_visits,
        "total_visits": total_visits,
        "completed_visits": total_visits,
        "farmers_covered": farmers_covered,
        "distance_today_km": round(distance_today_km, 2),
        "route_points_today": route_points_today,
        "pending_sync": 0,
        "pending_visits": 0,
        "active_visit": None,
        "work_status": work_status,
        "workday_id": workday_id,
    }
