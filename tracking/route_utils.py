"""Route history helpers for admin maps and mobile sync."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from django.db.models import QuerySet

from .models import LocationLog


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
        LocationLog.objects.filter(
            user_id=user_id,
            recorded_at__date=target_date,
        )
        .order_by("recorded_at", "id")
    )


def build_route_points(qs: QuerySet) -> list[dict[str, Any]]:
    return [serialize_route_point(row) for row in qs]


def compute_route_distance_km(route: list[dict[str, Any]]) -> float:
    total = 0.0
    for i in range(1, len(route)):
        total += distance_km(
            route[i - 1]["latitude"],
            route[i - 1]["longitude"],
            route[i]["latitude"],
            route[i]["longitude"],
        )
    return round(total, 2)


def build_admin_route_data(
    *,
    employee_id: str,
    user_id: int,
    target_date: date,
    route: list[dict[str, Any]],
) -> dict[str, Any]:
    """Payload for admin route API (includes legacy keys)."""
    return {
        "date": str(target_date),
        "employee_id": employee_id,
        "user_id": user_id,
        "total_points": len(route),
        "total_distance_km": compute_route_distance_km(route),
        "route": route,
        "points": route,
        "locations": route,
    }
