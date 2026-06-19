"""Daily rollup for admin field-force tracking (workday + visits + route)."""

from __future__ import annotations

from datetime import date, datetime, time

from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tracking.duty_service import get_route_points_for_date, serialize_route_point_model
from tracking.models import WorkDay
from tracking.route_utils import (
    build_route_points,
    compute_route_distance_km,
    distance_km,
    get_route_queryset,
)
from tracking.status_utils import (
    MOVEMENT_MIN_DISTANCE_KM,
    MOVEMENT_MIN_SPEED_KMH,
    MOVEMENT_WINDOW_MINUTES,
)
from tracking.workday_utils import workday_scheduled_end
from visits.submitted import submitted_visits_qs


def _format_duration(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def _point_timestamp(point: dict) -> datetime | None:
    raw = point.get("recorded_at") or point.get("captured_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    return parse_datetime(str(raw))


def compute_work_hours_seconds(
    workdays: list[WorkDay],
    target_date: date,
    *,
    now=None,
) -> int:
    """Sum workday clock time (start → end) for all sessions on target_date."""
    now = now or timezone.now()
    total = 0
    for wd in workdays:
        if not wd.start_time:
            continue
        start = wd.start_time
        if wd.end_time:
            end = wd.end_time
        elif wd.is_active and wd.date == now.date():
            end = min(now, workday_scheduled_end(wd.start_time))
        else:
            end = workday_scheduled_end(wd.start_time)
        total += max(int((end - start).total_seconds()), 0)
    return total


def compute_idle_minutes(route: list[dict]) -> int:
    """
    Cumulative idle time from consecutive GPS points using the same thresholds
    as live movement_status (status_utils).
    """
    if len(route) < 2:
        return 0

    idle_seconds = 0
    for i in range(len(route) - 1):
        p1, p2 = route[i], route[i + 1]
        t1 = _point_timestamp(p1)
        t2 = _point_timestamp(p2)
        if not t1 or not t2:
            continue
        dt = (t2 - t1).total_seconds()
        if dt <= 0:
            continue
        dist = distance_km(
            float(p1["latitude"]),
            float(p1["longitude"]),
            float(p2["latitude"]),
            float(p2["longitude"]),
        )
        speed_kmh = (dist / dt) * 3600
        low_movement = (
            dist < MOVEMENT_MIN_DISTANCE_KM and speed_kmh < MOVEMENT_MIN_SPEED_KMH
        )
        long_gap_still = (
            dt > MOVEMENT_WINDOW_MINUTES * 60 and dist < MOVEMENT_MIN_DISTANCE_KM
        )
        if low_movement or long_gap_still:
            idle_seconds += dt
    return int(idle_seconds // 60)


def _visit_timestamp(visit) -> datetime | None:
    if visit.visit_date and visit.visit_time:
        return datetime.combine(
            visit.visit_date,
            visit.visit_time,
            tzinfo=timezone.get_current_timezone(),
        )
    if visit.created_at:
        return visit.created_at
    if visit.visit_date:
        return datetime.combine(
            visit.visit_date,
            time.min,
            tzinfo=timezone.get_current_timezone(),
        )
    return None


def build_visit_stops(user_id: int, target_date: date) -> list[dict]:
    """Visit markers for route replay timeline (chronological)."""
    visits = (
        submitted_visits_qs()
        .filter(employee_id=user_id, visit_date=target_date)
        .select_related("farmer", "village", "crop")
        .order_by("visit_time", "created_at", "id")
    )
    stops = []
    for visit in visits:
        farmer_name = visit.farmer_name
        if not farmer_name and visit.farmer_id:
            farmer_name = visit.farmer.name
        village_name = visit.village.name if visit.village_id else None
        ts = _visit_timestamp(visit)
        stop = {
            "type": "visit",
            "visit_id": visit.id,
            "timestamp": ts.isoformat() if ts else None,
            "latitude": float(visit.latitude) if visit.latitude is not None else None,
            "longitude": float(visit.longitude) if visit.longitude is not None else None,
            "farmer_id": visit.farmer_id,
            "farmer_name": farmer_name,
            "village_id": visit.village_id,
            "village_name": village_name,
        }
        if visit.crop_id:
            stop["crop_id"] = visit.crop_id
            stop["crop_name"] = getattr(visit.crop, "name", None)
        stops.append(stop)
    return stops


def build_employee_daily_summary(
    *,
    user_id: int,
    employee_id: str,
    target_date: date,
    now=None,
) -> dict:
    """Aggregate daily metrics for one employee (computed on read)."""
    now = now or timezone.now()

    workdays = list(
        WorkDay.objects.filter(user_id=user_id, date=target_date).order_by("start_time")
    )

    duty_route = [
        serialize_route_point_model(p)
        for p in get_route_points_for_date(user_id, target_date)
    ]
    if duty_route:
        route = duty_route
    else:
        route_qs = get_route_queryset(user_id=user_id, target_date=target_date)
        route = build_route_points(route_qs)

    work_seconds = compute_work_hours_seconds(workdays, target_date, now=now)
    distance_km = compute_route_distance_km(route)
    idle_minutes = compute_idle_minutes(route)

    visits_qs = submitted_visits_qs().filter(
        employee_id=user_id,
        visit_date=target_date,
    )
    visits_completed = visits_qs.count()
    farmers_covered = (
        visits_qs.filter(farmer_id__isnull=False)
        .values("farmer_id")
        .distinct()
        .count()
    )
    villages_covered = (
        visits_qs.filter(village_id__isnull=False)
        .values("village_id")
        .distinct()
        .count()
    )

    return {
        "date": str(target_date),
        "user_id": user_id,
        "employee_id": employee_id,
        "work_hours": _format_duration(work_seconds),
        "work_hours_seconds": work_seconds,
        "distance_km": distance_km,
        "distance_travelled_km": distance_km,
        "visits_completed": visits_completed,
        "farmers_covered": farmers_covered,
        "villages_covered": villages_covered,
        "idle_minutes": idle_minutes,
        "workday_count": len(workdays),
        "route_point_count": len(route),
    }


class DailySummaryService:
    """Admin daily rollup for a single employee."""

    @staticmethod
    def for_employee(
        user: User,
        *,
        employee_id: str,
        target_date: date,
        now=None,
    ) -> dict:
        return build_employee_daily_summary(
            user_id=user.id,
            employee_id=employee_id,
            target_date=target_date,
            now=now,
        )
