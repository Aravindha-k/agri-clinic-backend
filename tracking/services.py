"""
tracking/services.py
─────────────────────
Business logic for GPS tracking and work-day management.
Redis is used as the live-location store; PostgreSQL holds the full history.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone

from .models import LocationLog, WorkDay
from .selectors import LIVE_LOCATION_TTL, _live_key, get_active_workday

logger = logging.getLogger(__name__)


class TrackingServiceError(Exception):
    """Raised for tracking domain business rule violations."""


# ──────────────────────────────────────────────────────────────
# Work-day management
# ──────────────────────────────────────────────────────────────


def start_workday(
    *,
    user: User,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> WorkDay:
    """
    Start a work session for the employee.
    Idempotent: returns the existing active session if one exists.
    """
    existing = get_active_workday(user)
    if existing:
        logger.info(
            "WorkDay already active for user_id=%s, returning existing", user.pk
        )
        return existing

    today = date.today()
    workday = WorkDay.objects.create(
        user=user,
        date=today,
        start_time=timezone.now(),
        latitude=latitude,
        longitude=longitude,
        is_active=True,
        last_heartbeat=timezone.now(),
    )
    logger.info("WorkDay started: user_id=%s workday_id=%s", user.pk, workday.pk)
    return workday


def end_workday(*, user: User) -> Optional[WorkDay]:
    """End the active work session for the employee."""
    workday = get_active_workday(user)
    if not workday:
        logger.warning("No active workday found for user_id=%s", user.pk)
        return None

    workday.end_time = timezone.now()
    workday.is_active = False
    workday.save(update_fields=["end_time", "is_active"])

    # Evict from Redis
    cache.delete(_live_key(user.pk))

    logger.info("WorkDay ended: user_id=%s workday_id=%s", user.pk, workday.pk)
    return workday


# ──────────────────────────────────────────────────────────────
# Live location update (Redis + DB log)
# ──────────────────────────────────────────────────────────────


def update_location(
    *,
    user: User,
    latitude: float,
    longitude: float,
    accuracy: Optional[float] = None,
    battery_level: Optional[int] = None,
    recorded_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Store the employee's latest location in Redis (live map)
    and append to the PostgreSQL location log.

    Returns the payload stored in Redis.
    """
    workday = get_active_workday(user)
    if not workday:
        # Auto-start a workday if employee hasn't clocked in
        workday = start_workday(user=user, latitude=latitude, longitude=longitude)

    if recorded_at is None:
        recorded_at = timezone.now()

    # Persist to DB
    LocationLog.objects.create(
        user=user,
        workday=workday,
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        battery_level=battery_level,
        recorded_at=recorded_at,
    )

    # Update heartbeat
    workday.last_heartbeat = timezone.now()
    workday.save(update_fields=["last_heartbeat"])

    # Write to Redis
    payload: Dict[str, Any] = {
        "user_id": user.pk,
        "username": user.username,
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": accuracy,
        "battery_level": battery_level,
        "timestamp": recorded_at.isoformat(),
        "workday_id": workday.pk,
    }

    # Attach employee_id if available
    if hasattr(user, "employee_profile"):
        payload["employee_id"] = user.employee_profile.employee_id

    cache.set(_live_key(user.pk), payload, timeout=LIVE_LOCATION_TTL)

    logger.debug(
        "Location updated: user_id=%s lat=%s lng=%s",
        user.pk,
        latitude,
        longitude,
    )
    return payload
