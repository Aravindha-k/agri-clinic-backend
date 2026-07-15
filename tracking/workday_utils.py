"""Workday helpers. DutySession timer arithmetic lives in tracking.duty_timer."""

from __future__ import annotations

import logging
import warnings
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from tracking.duty_timer import (
    DURATION_LIMIT_SECONDS,
    expected_end_at,
    is_session_within_limit,
)
from tracking.models import WorkDay

logger = logging.getLogger(__name__)


def _live_cache_key(user_id: int) -> str:
    return f"tracking:live:{user_id}"


# Deprecated name — always derives from DURATION_LIMIT_SECONDS (duty_timer).
MAX_WORKDAY_DURATION = timedelta(seconds=DURATION_LIMIT_SECONDS)

# Orphan WorkDay safety: never treat stale active rows as valid forever.
MAX_WORKDAY_STALE_AGE = timedelta(days=2)

WORKDAY_EXPIRED_MESSAGE = (
    "Workday not started or was auto-ended after 9 hours. Start a new workday."
)


def workday_scheduled_end(start_time, *, duration=None):
    """
    Deprecated compatibility wrapper.

    Prefer tracking.duty_timer.expected_end_at. No local 9-hour arithmetic.
    """
    warnings.warn(
        "workday_scheduled_end is deprecated; use tracking.duty_timer.expected_end_at",
        DeprecationWarning,
        stacklevel=2,
    )
    if duration is not None:
        return expected_end_at(
            start_time, duration_limit_seconds=int(duration.total_seconds())
        )
    return expected_end_at(start_time)


def is_workday_within_duration(workday: WorkDay | None, now=None) -> bool:
    """
    Deprecated compatibility wrapper.

    Prefer tracking.duty_timer.is_session_within_limit / is_duty_overdue.
    """
    warnings.warn(
        "is_workday_within_duration is deprecated; use tracking.duty_timer helpers",
        DeprecationWarning,
        stacklevel=2,
    )
    if not workday:
        return False
    if now is None:
        now = timezone.now()
    # Stale-age guard is operational (not a second 9h formula).
    if workday.start_time and (now - workday.start_time > MAX_WORKDAY_STALE_AGE):
        return False
    return is_session_within_limit(
        workday.start_time, is_active=bool(workday.is_active), now=now
    )


def _expire_orphan_workday_row(workday: WorkDay, *, now=None) -> None:
    """Close an active WorkDay that has no linking active DutySession."""
    now = now or timezone.now()
    workday.end_time = expected_end_at(workday.start_time)
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
    cutoff = now - timedelta(seconds=DURATION_LIMIT_SECONDS)
    orphans = (
        WorkDay.objects.filter(is_active=True, start_time__lte=cutoff).order_by("id")
    )
    for workday in orphans.iterator(chunk_size=200):
        from tracking.models import DutySession

        if DutySession.objects.filter(workday=workday, is_active=True).exists():
            continue
        if DutySession.objects.filter(user=workday.user, is_active=True).exists():
            continue
        _expire_orphan_workday_row(workday, now=now)
        count += 1
    if count:
        logger.info("expire_old_workdays closed %s session/workday row(s)", count)
    return count


def expire_overlong_workdays_for_user(user, *, now=None) -> int:
    """Lazy expiry for one user via DutySession (WorkDay synced through duty service)."""
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

    cutoff = now - timedelta(seconds=DURATION_LIMIT_SECONDS)
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
