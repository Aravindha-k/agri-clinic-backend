"""
tracking/selectors.py
──────────────────────
Read-only queries for the tracking domain.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import QuerySet

from .models import LocationLog, WorkDay

logger = logging.getLogger(__name__)

# Redis TTL for live locations (seconds)
LIVE_LOCATION_TTL = 15 * 60  # 15 minutes


# ──────────────────────────────────────────────────────────────
# Redis helpers
# ──────────────────────────────────────────────────────────────


def _live_key(user_id: int) -> str:
    return f"tracking:live:{user_id}"


def get_live_location(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Return the latest GPS location from Redis, or None if stale / not found.
    """
    raw = cache.get(_live_key(user_id))
    if raw is None:
        return None
    return raw if isinstance(raw, dict) else json.loads(raw)


def get_all_live_locations() -> List[Dict[str, Any]]:
    """
    Return live locations for ALL employees currently tracked in Redis.

    NOTE: Django's Redis cache backend does not expose pattern scanning,
    so we fetch active work-day users and probe Redis for each.
    """
    active_user_ids = (
        WorkDay.objects.filter(is_active=True)
        .values_list("user_id", flat=True)
        .distinct()
    )

    results = []
    for uid in active_user_ids:
        loc = get_live_location(uid)
        if loc:
            results.append(loc)
    return results


# ──────────────────────────────────────────────────────────────
# DB-backed location queries
# ──────────────────────────────────────────────────────────────


def get_location_logs(
    *,
    user: User,
    for_date: Optional[date] = None,
    workday_id: Optional[int] = None,
) -> QuerySet:
    qs = LocationLog.objects.select_related("user", "workday").filter(user=user)
    if for_date:
        qs = qs.filter(workday__date=for_date)
    if workday_id:
        qs = qs.filter(workday_id=workday_id)
    return qs.order_by("recorded_at")


def get_active_workday(user: User) -> Optional[WorkDay]:
    return WorkDay.objects.filter(user=user, is_active=True).order_by("-date").first()


def get_workday_history(user: User, limit: int = 30) -> QuerySet:
    return WorkDay.objects.filter(user=user).order_by("-date")[:limit]


def get_active_employees_on_field() -> QuerySet:
    """Return WorkDay records for employees currently clocked in."""
    return (
        WorkDay.objects.select_related("user", "user__employee_profile")
        .filter(is_active=True)
        .order_by("-date")
    )


def get_last_known_location(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Latest GPS for admin maps: Redis live cache first, then latest LocationLog.
    """
    live = get_live_location(user_id)
    if live and live.get("latitude") is not None:
        return {
            "latitude": live.get("latitude"),
            "longitude": live.get("longitude"),
            "recorded_at": live.get("timestamp"),
        }

    return (
        LocationLog.objects.filter(user_id=user_id)
        .order_by("-recorded_at")
        .values("latitude", "longitude", "recorded_at")
        .first()
    )
