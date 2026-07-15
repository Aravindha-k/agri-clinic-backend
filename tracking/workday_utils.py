"""Workday duration limits and helpers (DutySession is authoritative for expiry)."""

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


def _expire_orphan_workday_row(workday: WorkDay, *, now=None) -> None:
    """Close an active WorkDay that has no linking active DutySession."""
    now = now or timezone.now()
    workday.end_time = workday_scheduled_end(workday.start_time)
    workday.is_active = False
    workday.auto_ended = True
    workday.save(update_fields=["end_time", "is_active", "auto_ended"])
    cache.delete(_live_cache_key(workday.user_id))
    logger.info(
        "Orphan WorkDay auto-ended: user_id=%s workday_id=%s end_time=%s",
        workday.user_id,
        workday.pk,
        workday.end_time,
    )


def expire_old_workdays(*, now=None) -> int:
    """
    Prefer DutySession expiry; also close orphan active WorkDays without duty.
    """
    now = now or timezone.now()
    from tracking.duty_expiry import expire_overdue_duties

    count = expire_overdue_duties(now=now, trigger="expire_old_workdays")
    cutoff = now - MAX_WORKDAY_DURATION
    orphans = (
        WorkDay.objects.filter(is_active=True, start_time__lte=cutoff)
        .order_by("id")
    )
    for workday in orphans.iterator(chunk_size=200):
        from tracking.models import DutySession

        if DutySession.objects.filter(workday=workday, is_active=True).exists():
            continue
        if DutySession.objects.filter(
            user=workday.user, is_active=True
        ).exists():
            # Active duty exists (possibly different workday link) — leave for duty expiry
            continue
        _expire_orphan_workday_row(workday, now=now)
        count += 1
    if count:
        logger.info("expire_old_workdays closed %s session/workday row(s)", count)
    return count


def expire_overlong_workdays_for_user(user, *, now=None) -> int:
    """
    Lazy expiry for one user via DutySession (WorkDay synced through duty service).
    Returns the number of rows closed (duty and/or orphan workdays).
    """
    if not user or not getattr(user, "is_authenticated", True):
        return 0
    now = now or timezone.now()
    from tracking.duty_expiry import expire_overdue_duty_for_user
    from tracking.models import DutySession

    was_active = DutySession.objects.filter(user=user, is_active=True).exists()
    duty = expire_overdue_duty_for_user(user, now=now, trigger="lazy_user")
    count = 0
    if was_active and duty is not None and not duty.is_active and duty.auto_ended:
        count = 1

    cutoff = now - MAX_WORKDAY_DURATION
    qs = WorkDay.objects.filter(
        user=user, is_active=True, start_time__lte=cutoff
    ).order_by("id")
    for workday in qs:
        if DutySession.objects.filter(user=user, is_active=True).exists():
            break
        _expire_orphan_workday_row(workday, now=now)
        count += 1
    return count


def clear_live_tracking_for_user(user_id: int) -> None:
    cache.delete(_live_cache_key(user_id))
