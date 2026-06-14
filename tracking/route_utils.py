"""Route history helpers for admin maps and mobile sync."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q, QuerySet

from .models import LocationLog

# Max segment length counted toward distance (filters GPS jumps).
MAX_ROUTE_SEGMENT_KM = 5.0
DEFAULT_ROUTE_DISPLAY_LIMIT = 2000
MAX_ROUTE_DISPLAY_LIMIT = 10000
SIMPLIFY_THRESHOLD_POINTS = 500


def distance_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_valid_coordinate(lat, lng) -> bool:
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return False
    if lat_f == 0 and lng_f == 0:
        return False
    return -90 <= lat_f <= 90 and -180 <= lng_f <= 180


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def serialize_route_point(log: LocationLog | dict) -> dict[str, Any]:
    """Standard route point for admin map APIs."""
    if isinstance(log, LocationLog):
        captured = log.recorded_at
        created = log.created_at
        return {
            "id": log.id,
            "user_id": log.user_id,
            "workday_id": log.workday_id,
            "latitude": float(log.latitude),
            "longitude": float(log.longitude),
            "accuracy": log.accuracy,
            "speed": log.speed,
            "heading": log.heading,
            "captured_at": _iso(captured),
            "created_at": _iso(created),
            "recorded_at": _iso(captured),
            "is_suspicious": log.is_suspicious,
        }

    captured = log.get("recorded_at")
    return {
        "id": log.get("id"),
        "user_id": log.get("user_id"),
        "workday_id": log.get("workday_id"),
        "latitude": float(log["latitude"]),
        "longitude": float(log["longitude"]),
        "accuracy": log.get("accuracy"),
        "speed": log.get("speed"),
        "heading": log.get("heading"),
        "captured_at": _iso(captured),
        "created_at": _iso(log.get("created_at")),
        "recorded_at": _iso(captured),
        "is_suspicious": log.get("is_suspicious", False),
    }


def get_route_queryset(*, user_id: int, target_date: date) -> QuerySet:
    """LocationLog rows for one employee on one calendar date, chronological."""
    return (
        LocationLog.objects.filter(user_id=user_id)
        .filter(
            Q(recorded_at__date=target_date) | Q(workday__date=target_date)
        )
        .order_by("recorded_at", "id")
    )


def build_route_points(qs: QuerySet) -> list[dict[str, Any]]:
    return [serialize_route_point(row) for row in qs]


def compute_route_distance_km(
    route: list[dict[str, Any]],
    *,
    max_segment_km: float = MAX_ROUTE_SEGMENT_KM,
    skip_suspicious: bool = False,
) -> float:
    """
    Sum Haversine segments between ordered points.
    Skips invalid coordinates and GPS jumps (> max_segment_km).
    Suspicious points are still counted unless skip_suspicious=True.
    """
    if len(route) < 2:
        return 0.0

    total = 0.0
    prev = None
    for point in route:
        if skip_suspicious and point.get("is_suspicious"):
            prev = None
            continue
        lat = point.get("latitude")
        lng = point.get("longitude")
        if not is_valid_coordinate(lat, lng):
            prev = None
            continue
        if prev is not None:
            segment = distance_km(prev[0], prev[1], lat, lng)
            if segment <= max_segment_km:
                total += segment
            else:
                prev = (lat, lng)
                continue
        prev = (lat, lng)
    return round(total, 2)


def simplify_route_uniform(
    route: list[dict[str, Any]], *, max_points: int
) -> list[dict[str, Any]]:
    """Decimate route for map display; raw LocationLog rows are never modified."""
    if max_points <= 0 or len(route) <= max_points:
        return route
    if max_points == 1:
        return [route[0]]
    step = (len(route) - 1) / (max_points - 1)
    indices = {0, len(route) - 1}
    for i in range(1, max_points - 1):
        indices.add(int(round(i * step)))
    ordered = sorted(indices)
    return [route[i] for i in ordered]


@dataclass(frozen=True)
class RouteDisplayOptions:
    limit: int = DEFAULT_ROUTE_DISPLAY_LIMIT
    simplify: bool = False

    @classmethod
    def from_request_params(
        cls,
        *,
        limit_raw: str | None,
        simplify_raw: str | None,
    ) -> RouteDisplayOptions:
        limit = DEFAULT_ROUTE_DISPLAY_LIMIT
        if limit_raw is not None:
            try:
                limit = max(1, min(int(limit_raw), MAX_ROUTE_DISPLAY_LIMIT))
            except (TypeError, ValueError):
                limit = DEFAULT_ROUTE_DISPLAY_LIMIT
        simplify = str(simplify_raw or "").lower() in ("1", "true", "yes")
        return cls(limit=limit, simplify=simplify)


def apply_route_display(
    route: list[dict[str, Any]], options: RouteDisplayOptions
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return display route + metadata (raw count preserved)."""
    raw_count = len(route)
    display = route
    simplified = False

    if options.simplify and raw_count > SIMPLIFY_THRESHOLD_POINTS:
        target = min(options.limit, SIMPLIFY_THRESHOLD_POINTS)
        display = simplify_route_uniform(route, max_points=target)
        simplified = True
    elif raw_count > options.limit:
        display = simplify_route_uniform(route, max_points=options.limit)
        simplified = True

    meta = {
        "raw_point_count": raw_count,
        "display_point_count": len(display),
        "simplified": simplified,
        "limit": options.limit,
        "simplify_requested": options.simplify,
    }
    return display, meta


def build_route_polyline(route: list[dict[str, Any]]) -> list[list[float]]:
    """[[lat, lng], ...] for map polylines."""
    poly = []
    for p in route:
        if is_valid_coordinate(p.get("latitude"), p.get("longitude")):
            poly.append([p["latitude"], p["longitude"]])
    return poly


def _format_duration(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def build_admin_route_data(
    *,
    employee_id: str,
    user_id: int,
    target_date: date,
    route: list[dict[str, Any]],
    workdays: list | None = None,
    display_meta: dict[str, Any] | None = None,
    raw_route: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Payload for admin route API (includes legacy keys + polyline)."""
    meta = display_meta or {}
    raw_route = raw_route if raw_route is not None else route
    distance_route = raw_route
    start_time = raw_route[0]["captured_at"] if raw_route else None
    end_time = raw_route[-1]["captured_at"] if raw_route else None
    duration_seconds = 0
    if (
        len(raw_route) >= 2
        and raw_route[0].get("captured_at")
        and raw_route[-1].get("captured_at")
    ):
        from django.utils.dateparse import parse_datetime

        t0 = parse_datetime(raw_route[0]["captured_at"])
        t1 = parse_datetime(raw_route[-1]["captured_at"])
        if t0 and t1:
            duration_seconds = max(int((t1 - t0).total_seconds()), 0)

    workday_start = None
    workday_end = None
    if workdays:
        starts = [w.start_time for w in workdays if w.start_time]
        ends = [w.end_time for w in workdays if w.end_time]
        if starts:
            workday_start = min(starts).isoformat()
        if ends:
            workday_end = max(ends).isoformat()
        elif starts:
            from .workday_utils import workday_scheduled_end

            workday_end = workday_scheduled_end(max(starts)).isoformat()

    raw_count = meta.get("raw_point_count", len(raw_route))
    return {
        "date": str(target_date),
        "employee_id": employee_id,
        "user_id": user_id,
        "total_points": raw_count,
        "raw_point_count": raw_count,
        "display_point_count": meta.get("display_point_count", len(route)),
        "simplified": meta.get("simplified", False),
        "distance_km": compute_route_distance_km(distance_route),
        "total_distance_km": compute_route_distance_km(distance_route),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "duration": _format_duration(duration_seconds),
        "workday_start_time": workday_start,
        "workday_end_time": workday_end,
        "route": route,
        "points": route,
        "locations": route,
        "polyline": build_route_polyline(route),
    }
