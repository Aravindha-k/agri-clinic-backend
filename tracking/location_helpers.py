"""Shared helpers for location push / bulk upload."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from tracking.models import LocationLog, WorkDay
from tracking.workday_utils import expire_overlong_workdays_for_user

logger = logging.getLogger(__name__)

MAX_ACCURACY_METERS = 200


def resolve_workday_for_location(user, workday_id: int | None = None) -> WorkDay:
    """
    Resolve target workday for a location point.
    Uses explicit workday_id when provided; otherwise the user's active workday.
    """
    expire_overlong_workdays_for_user(user)

    if workday_id is not None:
        try:
            workday = WorkDay.objects.get(pk=workday_id, user=user)
        except WorkDay.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"workday_id": "Workday not found for this user."}
            ) from exc
        if not workday.is_active:
            raise serializers.ValidationError(
                {"workday_id": "Workday is not active."}
            )
        return workday

    workday = (
        WorkDay.objects.filter(user=user, is_active=True)
        .order_by("-start_time")
        .first()
    )
    if not workday:
        raise serializers.ValidationError("No active workday")
    return workday


def normalize_recorded_at(validated_data: dict):
    """Pick device timestamp from captured_at / recorded_at / timestamp."""
    return (
        validated_data.get("captured_at")
        or validated_data.get("recorded_at")
        or validated_data.get("timestamp")
        or timezone.now()
    )


def workday_has_location_points(workday: WorkDay) -> bool:
    return LocationLog.objects.filter(workday=workday).exists()


def is_duplicate_location_point(
    workday: WorkDay,
    latitude,
    longitude,
    recorded_at,
) -> bool:
    """Reject exact duplicate lat/lng/timestamp for the same workday."""
    lat = Decimal(str(latitude)).quantize(Decimal("0.000001"))
    lng = Decimal(str(longitude)).quantize(Decimal("0.000001"))
    return LocationLog.objects.filter(
        workday=workday,
        latitude=lat,
        longitude=lng,
        recorded_at=recorded_at,
    ).exists()


def validate_movement_point(
    *,
    workday: WorkDay,
    latitude,
    longitude,
    recorded_at,
    accuracy: float | None,
) -> None:
    """
    Backend safety filter for movement-based GPS points.
    Mobile filters movement; backend only rejects clearly bad data.
    """
    if accuracy is not None:
        try:
            accuracy_f = float(accuracy)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError(
                {"accuracy": "Accuracy must be a number."}
            ) from exc
        if accuracy_f > MAX_ACCURACY_METERS and workday_has_location_points(workday):
            raise serializers.ValidationError(
                {
                    "accuracy": (
                        f"Accuracy {accuracy_f:.0f}m exceeds {MAX_ACCURACY_METERS}m "
                        "(first point for workday is allowed)."
                    )
                }
            )

    if is_duplicate_location_point(workday, latitude, longitude, recorded_at):
        raise serializers.ValidationError(
            "Duplicate location point (same latitude, longitude, and timestamp)."
        )


def workday_distance_km(workday_id: int) -> float:
    from tracking.route_utils import build_route_points, compute_route_distance_km

    qs = LocationLog.objects.filter(workday_id=workday_id).order_by("recorded_at", "id")
    route = build_route_points(qs)
    return compute_route_distance_km(route)


def log_location_saved(
    *,
    source: str,
    user_id: int,
    workday_id: int,
    location: LocationLog,
    recorded_at,
) -> int:
    """Structured debug log after a LocationLog row is created."""
    total = LocationLog.objects.filter(workday_id=workday_id).count()
    distance_km = workday_distance_km(workday_id)
    logger.info(
        "LocationReceived source=%s employee_id=%s workday_id=%s "
        "location_log_id=%s lat=%s lng=%s timestamp=%s "
        "total_points=%s distance_km=%s",
        source,
        user_id,
        workday_id,
        location.id,
        location.latitude,
        location.longitude,
        recorded_at,
        total,
        distance_km,
    )
    return total
