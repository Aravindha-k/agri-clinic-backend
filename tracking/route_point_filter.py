"""When to persist EmployeeRoutePoint (avoid saving every 5s GPS ping)."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from tracking.models import EmployeeRoutePoint
from tracking.route_utils import distance_km

# Save route point if moved >= MIN_DISTANCE_METERS or >= MIN_INTERVAL_SECONDS since last point.
MIN_ROUTE_DISTANCE_METERS = 35
MIN_ROUTE_INTERVAL_SECONDS = 90


def _meters_between(lat1, lon1, lat2, lon2) -> float:
    return distance_km(lat1, lon1, lat2, lon2) * 1000.0


def should_save_route_point(
    *,
    duty_session_id: int,
    latitude: float,
    longitude: float,
    recorded_at: datetime | None = None,
    force: bool = False,
) -> bool:
    """Return True if a new GPS route point should be stored."""
    if force:
        return True

    recorded_at = recorded_at or timezone.now()
    last = (
        EmployeeRoutePoint.objects.filter(
            duty_session_id=duty_session_id,
            point_type=EmployeeRoutePoint.POINT_GPS,
        )
        .order_by("-recorded_at", "-id")
        .first()
    )
    if not last:
        return True

    elapsed = (recorded_at - last.recorded_at).total_seconds()
    if elapsed >= MIN_ROUTE_INTERVAL_SECONDS:
        return True

    meters = _meters_between(
        float(last.latitude),
        float(last.longitude),
        latitude,
        longitude,
    )
    return meters >= MIN_ROUTE_DISTANCE_METERS
