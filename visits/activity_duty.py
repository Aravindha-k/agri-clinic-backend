"""
Bulk Today duty aggregation for Admin visit activity-summary.

Source of truth: tracking.DutySession only.
Auth login / GPS last-seen / Visit timestamps are never used as duty bounds.

Duty objects are authoritative for single-day (Today) ranges only.
Multi-day Week/Month callers should pass include_duty=False and attach duty=null.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from django.utils import timezone

from tracking.duty_timer import (
    COMPLETION_AUTO_EXPIRED,
    DURATION_LIMIT_SECONDS,
    effective_end_from_bounds,
    expected_end_at,
)
from tracking.models import DutySession

STATUS_ON_DUTY = "ON_DUTY"
STATUS_ENDED = "ENDED"
STATUS_AUTO_ENDED = "AUTO_ENDED"
STATUS_NOT_STARTED = "NOT_STARTED"


def not_started_duty() -> dict[str, Any]:
    return {
        "status": STATUS_NOT_STARTED,
        "start_time": None,
        "end_time": None,
        "duration_seconds": 0,
        "completion_reason": None,
        "session_count": 0,
        "duration_limit_seconds": DURATION_LIMIT_SECONDS,
    }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _session_duration_seconds(
    *,
    start_time: datetime | None,
    end_time: datetime | None,
    is_active: bool,
    now: datetime,
) -> int:
    if not start_time:
        return 0
    effective = effective_end_from_bounds(
        start_time,
        end_time=end_time,
        is_active=is_active,
        now=now,
        duration_limit_seconds=DURATION_LIMIT_SECONDS,
    )
    if effective is None:
        return 0
    seconds = int(max(0, (effective - start_time).total_seconds()))
    return min(seconds, DURATION_LIMIT_SECONDS)


def aggregate_employee_duty(
    sessions: list[DutySession],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Aggregate one employee's DutySession rows for a single business date.

    duration_seconds = SUM over sessions of capped (effective_end - start).
    status prefers any active session → ON_DUTY; else latest session outcome.
    """
    now = now or timezone.now()
    if not sessions:
        return not_started_duty()

    ordered = sorted(
        sessions,
        key=lambda s: (s.start_time or datetime.min.replace(tzinfo=now.tzinfo), s.pk or 0),
    )
    first_start = ordered[0].start_time
    active = [s for s in ordered if s.is_active]
    ended_times = [s.end_time for s in ordered if s.end_time is not None]
    last_end = max(ended_times) if ended_times else None

    duration = 0
    for session in ordered:
        duration += _session_duration_seconds(
            start_time=session.start_time,
            end_time=session.end_time,
            is_active=bool(session.is_active),
            now=now,
        )

    if active:
        status = STATUS_ON_DUTY
        completion_reason = None
        end_time = None
    else:
        latest = ordered[-1]
        reason = (latest.completion_reason or "").strip().upper() or None
        if latest.auto_ended or reason == COMPLETION_AUTO_EXPIRED:
            status = STATUS_AUTO_ENDED
            completion_reason = reason or COMPLETION_AUTO_EXPIRED
        else:
            status = STATUS_ENDED
            completion_reason = reason
        end_time = last_end or latest.end_time

    return {
        "status": status,
        "start_time": _iso(first_start),
        "end_time": _iso(end_time),
        "duration_seconds": int(duration),
        "completion_reason": completion_reason,
        "session_count": len(ordered),
        "duration_limit_seconds": DURATION_LIMIT_SECONDS,
    }


def bulk_duty_by_user(
    user_ids: list[int],
    *,
    business_date: date,
    now: datetime | None = None,
) -> dict[int, dict[str, Any]]:
    """
    One DutySession query for the roster + business date.

    Returns a map of user_id → duty payload. Missing users are NOT_STARTED.
    """
    now = now or timezone.now()
    result = {uid: not_started_duty() for uid in user_ids}
    if not user_ids:
        return result

    sessions = list(
        DutySession.objects.filter(
            user_id__in=user_ids,
            date=business_date,
        ).only(
            "id",
            "user_id",
            "date",
            "start_time",
            "end_time",
            "is_active",
            "auto_ended",
            "completion_reason",
        )
    )
    by_user: dict[int, list[DutySession]] = defaultdict(list)
    for session in sessions:
        by_user[session.user_id].append(session)

    for user_id, rows in by_user.items():
        result[user_id] = aggregate_employee_duty(rows, now=now)
    return result


# Re-export for tests / callers that need the cap constant without magic numbers.
__all__ = [
    "STATUS_ON_DUTY",
    "STATUS_ENDED",
    "STATUS_AUTO_ENDED",
    "STATUS_NOT_STARTED",
    "DURATION_LIMIT_SECONDS",
    "expected_end_at",
    "not_started_duty",
    "aggregate_employee_duty",
    "bulk_duty_by_user",
]
