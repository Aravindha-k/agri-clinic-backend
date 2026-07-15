"""Canonical overdue DutySession auto-completion (idempotent)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from tracking.duty_timer import (
    COMPLETION_AUTO_EXPIRED,
    DURATION_LIMIT_SECONDS,
    expected_end_at,
    is_duty_overdue,
)
from tracking.models import DutySession, WorkDay
from tracking.workday_utils import clear_live_tracking_for_user

logger = logging.getLogger(__name__)


def _sync_workday_auto_complete(duty: DutySession, ended_at: datetime) -> None:
    if not duty.workday_id:
        return
    WorkDay.objects.filter(pk=duty.workday_id).update(
        end_time=ended_at,
        is_active=False,
        auto_ended=True,
    )


def complete_duty_as_auto_expired(
    duty: DutySession,
    *,
    now: datetime | None = None,
    trigger: str = "unknown",
) -> DutySession:
    """
    Finalize one DutySession as AUTO_EXPIRED.

    ended_at = start_time + 9h (expected_end_at), not wall-clock job time.
    Safe to call repeatedly on already-completed rows.
    """
    now = now or timezone.now()
    if not duty.is_active:
        return duty

    ended_at = expected_end_at(duty.start_time)
    duty.end_time = ended_at
    duty.is_active = False
    duty.auto_ended = True
    duty.completion_reason = COMPLETION_AUTO_EXPIRED
    duty.save(
        update_fields=[
            "end_time",
            "is_active",
            "auto_ended",
            "completion_reason",
        ]
    )
    _sync_workday_auto_complete(duty, ended_at)
    clear_live_tracking_for_user(duty.user_id)
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception:
        logger.exception(
            "Dashboard cache invalidation failed after duty auto-complete"
        )
    logger.info(
        "event=duty_auto_completed duty_session_id=%s user_id=%s "
        "start_time=%s expected_end_at=%s completed_at=%s trigger=%s "
        "duration_limit_seconds=%s",
        duty.pk,
        duty.user_id,
        duty.start_time.isoformat() if duty.start_time else None,
        ended_at.isoformat(),
        now.isoformat(),
        trigger,
        DURATION_LIMIT_SECONDS,
    )
    return duty


@transaction.atomic
def expire_overdue_duty_locked(
    duty_id: int,
    *,
    now: datetime | None = None,
    trigger: str = "unknown",
) -> DutySession | None:
    """Lock one duty by id and auto-complete if still active and overdue."""
    now = now or timezone.now()
    # Do not select_related(workday): Postgres rejects FOR UPDATE on nullable outer joins.
    duty = (
        DutySession.objects.select_for_update()
        .filter(pk=duty_id)
        .first()
    )
    if duty is None:
        return None
    if not duty.is_active:
        return duty
    if not is_duty_overdue(duty, now=now):
        return duty
    return complete_duty_as_auto_expired(duty, now=now, trigger=trigger)


@transaction.atomic
def expire_overdue_duty_for_user(
    user: User,
    *,
    now: datetime | None = None,
    trigger: str = "lazy_current",
) -> DutySession | None:
    """
    Lazy expiry for one user. Returns the duty after expiry attempt
    (completed or still-active / None).
    """
    if not user or not getattr(user, "pk", None):
        return None
    now = now or timezone.now()
    # No select_related: nullable workday FK + FOR UPDATE fails on Postgres.
    duty = (
        DutySession.objects.select_for_update()
        .filter(user=user, is_active=True)
        .order_by("-start_time")
        .first()
    )
    if duty is None:
        return None
    if is_duty_overdue(duty, now=now):
        return complete_duty_as_auto_expired(duty, now=now, trigger=trigger)
    return duty


def expire_overdue_duties(
    *, now: datetime | None = None, trigger: str = "celery"
) -> int:
    """
    Bulk expiry used by Celery beat and management commands.

    Uses per-row select_for_update(skip_locked=True) so overlapping workers
    do not double-complete.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=DURATION_LIMIT_SECONDS)
    ids = list(
        DutySession.objects.filter(is_active=True, start_time__lte=cutoff)
        .order_by("id")
        .values_list("id", flat=True)[:2000]
    )
    count = 0
    for duty_id in ids:
        with transaction.atomic():
            duty = (
                DutySession.objects.select_for_update(skip_locked=True)
                .filter(pk=duty_id, is_active=True)
                .first()
            )
            if duty is None:
                continue
            if not is_duty_overdue(duty, now=now):
                continue
            complete_duty_as_auto_expired(duty, now=now, trigger=trigger)
            count += 1
    if count:
        logger.info(
            "event=duty_auto_completed_batch count=%s trigger=%s", count, trigger
        )
    return count
