"""Workday duration limits and auto-end helpers."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import WorkDay

logger = logging.getLogger(__name__)


def _live_cache_key(user_id: int) -> str:
    return f"tracking:live:{user_id}"

MAX_WORKDAY_DURATION = timedelta(hours=9)
# Belt-and-suspenders: never treat a workday as active after 2 calendar days.
MAX_WORKDAY_STALE_AGE = timedelta(days=2)

WORKDAY_EXPIRED_MESSAGE = (
    "Workday not started or was auto-ended after 9 hours. Start a new workday."
)


def workday_scheduled_end(start_time, *, duration=None):
    """Canonical end instant for a workday that runs the full allowed shift."""
    duration = duration or MAX_WORKDAY_DURATION
    return start_time + duration


def is_workday_within_duration(workday: WorkDay | None, now=None) -> bool:
    """
    True only if workday is marked active and still inside the 9-hour window.
    Accepts optional ``now`` (positional or keyword) for deterministic tests/admin views.
    """
    if not workday or not workday.is_active:
        return False
    if now is None:
        now = timezone.now()
    if now - workday.start_time > MAX_WORKDAY_STALE_AGE:
        return False
    return workday.start_time + MAX_WORKDAY_DURATION > now


def _expire_workday_row(workday: WorkDay, *, now=None) -> None:
    """Close one overlong workday and evict live tracking cache."""
    now = now or timezone.now()
    workday.end_time = workday_scheduled_end(workday.start_time)
    workday.is_active = False
    workday.auto_ended = True
    workday.save(update_fields=["end_time", "is_active", "auto_ended"])
    cache.delete(_live_cache_key(workday.user_id))
    logger.info(
        "WorkDay auto-ended: user_id=%s workday_id=%s end_time=%s",
        workday.user_id,
        workday.pk,
        workday.end_time,
    )


def expire_old_workdays(*, now=None) -> int:
    """
    End all active workdays whose start_time is older than MAX_WORKDAY_DURATION.
    Sets end_time = start_time + 9 hours (not wall-clock now).
    Clears Redis live-location keys for affected employees.
    """
    now = now or timezone.now()
    cutoff = now - MAX_WORKDAY_DURATION
    qs = (
        WorkDay.objects.filter(is_active=True, start_time__lte=cutoff)
        .select_related("user")
        .order_by("id")
    )
    count = 0
    for workday in qs.iterator(chunk_size=200):
        _expire_workday_row(workday, now=now)
        count += 1
    if count:
        logger.info("expire_old_workdays closed %s workday(s)", count)
    return count


def expire_overlong_workdays_for_user(user, *, now=None) -> int:
    """
    End active workdays for one user that exceeded MAX_WORKDAY_DURATION.
    Returns the number of workdays closed.
    """
    if not user or not getattr(user, "is_authenticated", True):
        return 0
    now = now or timezone.now()
    cutoff = now - MAX_WORKDAY_DURATION
    qs = WorkDay.objects.filter(
        user=user, is_active=True, start_time__lte=cutoff
    ).order_by("id")
    count = 0
    for workday in qs:
        _expire_workday_row(workday, now=now)
        count += 1
    return count


def clear_live_tracking_for_user(user_id: int) -> None:
    cache.delete(_live_cache_key(user_id))
