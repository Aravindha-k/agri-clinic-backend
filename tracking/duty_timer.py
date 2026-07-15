"""Canonical DutySession 9-hour timer calculations (server-authoritative).

Elapsed/remaining seconds use integer floor of total_seconds() for positive deltas.
This module owns the only DURATION_LIMIT_SECONDS / expected-end arithmetic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from tracking.models import DutySession

DURATION_LIMIT_SECONDS = 32400  # 9 hours — sole canonical duration constant

COMPLETION_MANUAL = "MANUAL"
COMPLETION_AUTO_EXPIRED = "AUTO_EXPIRED"

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_AUTO_COMPLETED = "AUTO_COMPLETED"


def expected_end_at(
    start_time: datetime,
    duration_limit_seconds: int = DURATION_LIMIT_SECONDS,
) -> datetime:
    """Scheduled/automatic completion instant for a duty that started at start_time."""
    return start_time + timedelta(seconds=duration_limit_seconds)


def _floor_seconds(delta) -> int:
    """Non-negative whole seconds; floor of total_seconds for positive values."""
    return max(0, int(delta.total_seconds()))


def effective_end_from_bounds(
    start_time: datetime | None,
    *,
    end_time: datetime | None = None,
    is_active: bool = True,
    now: datetime | None = None,
    duration_limit_seconds: int = DURATION_LIMIT_SECONDS,
) -> datetime | None:
    """
    Effective end for duration math.

    - Completed: preserve end_time
    - Active: min(server_now, expected_end_at)
    """
    if not start_time:
        return None
    now = now or timezone.now()
    expected = expected_end_at(start_time, duration_limit_seconds)
    if not is_active:
        return end_time
    return min(now, expected)


def is_session_within_limit(
    start_time: datetime | None,
    *,
    is_active: bool,
    now: datetime | None = None,
    duration_limit_seconds: int = DURATION_LIMIT_SECONDS,
) -> bool:
    """
    True only if the session is marked active and server_now is still before
    expected_end_at. Does not mutate rows.
    """
    if not is_active or not start_time:
        return False
    now = now or timezone.now()
    return now < expected_end_at(start_time, duration_limit_seconds)


def compute_session_timer(
    *,
    start_time: datetime | None,
    end_time: datetime | None = None,
    is_active: bool = False,
    auto_ended: bool = False,
    completion_reason: str | None = None,
    session_id: int | None = None,
    now: datetime | None = None,
    duration_limit_seconds: int = DURATION_LIMIT_SECONDS,
) -> dict[str, Any]:
    """
    Core timer fields without requiring a DutySession instance.

    Used by compute_duty_timer and rare WorkDay-only orphan display paths.
    """
    now = now or timezone.now()
    expected = (
        expected_end_at(start_time, duration_limit_seconds) if start_time else None
    )

    if is_active:
        effective = now
        if expected is not None and effective > expected:
            effective = expected
        elapsed = (
            min(_floor_seconds(effective - start_time), duration_limit_seconds)
            if start_time
            else 0
        )
        remaining = max(0, duration_limit_seconds - elapsed)
        ended_at = None
        is_expired = bool(expected and now >= expected)
        status = STATUS_ACTIVE
    else:
        ended_at = end_time
        if start_time and ended_at:
            elapsed = min(
                _floor_seconds(ended_at - start_time), duration_limit_seconds
            )
        else:
            elapsed = 0
        remaining = 0
        is_expired = bool(
            auto_ended or completion_reason == COMPLETION_AUTO_EXPIRED
        )
        if auto_ended or completion_reason == COMPLETION_AUTO_EXPIRED:
            status = STATUS_AUTO_COMPLETED
        elif start_time or end_time:
            status = STATUS_COMPLETED
        else:
            status = "NOT_STARTED"

    return {
        "id": session_id,
        "status": status,
        "start_time": start_time.isoformat() if start_time else None,
        "started_at": start_time.isoformat() if start_time else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "end_time": ended_at.isoformat() if ended_at else None,
        "duration_limit_seconds": duration_limit_seconds,
        "expected_end_at": expected.isoformat() if expected else None,
        "server_now": now.isoformat(),
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "is_expired": is_expired,
        "completion_reason": completion_reason,
        "auto_ended": bool(auto_ended),
        "is_active": bool(is_active),
        "_expected_end_at_dt": expected,
        "_effective_end_dt": (
            ended_at
            if not is_active
            else (min(now, expected) if expected else now)
        ),
        "_start_dt": start_time,
        "_server_now_dt": now,
    }


def duty_public_status(duty: DutySession) -> str:
    if duty.is_active:
        return STATUS_ACTIVE
    if duty.auto_ended or duty.completion_reason == COMPLETION_AUTO_EXPIRED:
        return STATUS_AUTO_COMPLETED
    return STATUS_COMPLETED


def is_duty_overdue(
    duty: DutySession,
    *,
    now: datetime | None = None,
    server_now: datetime | None = None,
) -> bool:
    now = server_now if server_now is not None else (now or timezone.now())
    if not duty.is_active or not duty.start_time:
        return False
    return now >= expected_end_at(duty.start_time)


def effective_duty_end(
    duty: DutySession,
    *,
    now: datetime | None = None,
    server_now: datetime | None = None,
) -> datetime | None:
    now = server_now if server_now is not None else (now or timezone.now())
    return effective_end_from_bounds(
        duty.start_time,
        end_time=duty.end_time,
        is_active=duty.is_active,
        now=now,
    )


def elapsed_seconds_for_duty(
    duty: DutySession,
    *,
    now: datetime | None = None,
    server_now: datetime | None = None,
) -> int:
    now = server_now if server_now is not None else (now or timezone.now())
    return compute_duty_timer(duty, now=now)["elapsed_seconds"]


def remaining_seconds_for_duty(
    duty: DutySession,
    *,
    now: datetime | None = None,
    server_now: datetime | None = None,
) -> int:
    now = server_now if server_now is not None else (now or timezone.now())
    return compute_duty_timer(duty, now=now)["remaining_seconds"]


def compute_duty_timer(
    duty: DutySession,
    *,
    now: datetime | None = None,
    server_now: datetime | None = None,
) -> dict[str, Any]:
    """
    Single source of timer fields for all duty / compatibility responses.

    Callers must auto-complete overdue active duties before serializing
    when they need a completed final state.
    """
    now = server_now if server_now is not None else (now or timezone.now())
    timer = compute_session_timer(
        start_time=duty.start_time,
        end_time=duty.end_time,
        is_active=duty.is_active,
        auto_ended=bool(duty.auto_ended),
        completion_reason=duty.completion_reason,
        session_id=duty.id,
        now=now,
    )
    timer["status"] = duty_public_status(duty)
    return timer


def empty_duty_timer(
    *, now: datetime | None = None, server_now: datetime | None = None
) -> dict[str, Any]:
    now = server_now if server_now is not None else (now or timezone.now())
    return {
        "id": None,
        "status": "NOT_STARTED",
        "start_time": None,
        "started_at": None,
        "ended_at": None,
        "end_time": None,
        "duration_limit_seconds": DURATION_LIMIT_SECONDS,
        "expected_end_at": None,
        "server_now": now.isoformat(),
        "elapsed_seconds": 0,
        "remaining_seconds": DURATION_LIMIT_SECONDS,
        "is_expired": False,
        "completion_reason": None,
        "auto_ended": False,
        "is_active": False,
        "_expected_end_at_dt": None,
        "_effective_end_dt": None,
        "_start_dt": None,
        "_server_now_dt": now,
    }


def format_elapsed_label(elapsed_seconds: int) -> str:
    elapsed_seconds = max(0, int(elapsed_seconds))
    hours, remainder = divmod(elapsed_seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def resolve_duty_for_workday(workday) -> DutySession | None:
    """Prefer the linked DutySession for a WorkDay (no timer arithmetic)."""
    if workday is None:
        return None
    duty = getattr(workday, "duty_session", None)
    if duty is not None:
        return duty
    return DutySession.objects.filter(workday_id=workday.pk).first()
