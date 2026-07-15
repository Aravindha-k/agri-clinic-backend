"""Canonical DutySession 9-hour timer calculations (server-authoritative).

Elapsed/remaining seconds use integer floor of total_seconds() for positive deltas.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from tracking.models import DutySession

DURATION_LIMIT_SECONDS = 32400  # 9 hours

COMPLETION_MANUAL = "MANUAL"
COMPLETION_AUTO_EXPIRED = "AUTO_EXPIRED"

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_AUTO_COMPLETED = "AUTO_COMPLETED"


def expected_end_at(start_time: datetime) -> datetime:
    return start_time + timedelta(seconds=DURATION_LIMIT_SECONDS)


def is_duty_overdue(duty: DutySession, *, now: datetime | None = None) -> bool:
    if not duty.is_active or not duty.start_time:
        return False
    now = now or timezone.now()
    return now >= expected_end_at(duty.start_time)


def duty_public_status(duty: DutySession) -> str:
    if duty.is_active:
        return STATUS_ACTIVE
    if duty.auto_ended or duty.completion_reason == COMPLETION_AUTO_EXPIRED:
        return STATUS_AUTO_COMPLETED
    return STATUS_COMPLETED


def _floor_seconds(delta) -> int:
    """Non-negative whole seconds; floor of total_seconds for positive values."""
    return max(0, int(delta.total_seconds()))


def compute_duty_timer(
    duty: DutySession, *, now: datetime | None = None
) -> dict[str, Any]:
    """
    Single source of timer fields for all duty / compatibility responses.

    Callers must auto-complete overdue active duties before serializing
    when they need a completed final state.
    """
    now = now or timezone.now()
    start = duty.start_time
    expected = expected_end_at(start) if start else None

    if duty.is_active:
        effective = now
        if expected is not None and effective > expected:
            effective = expected
        elapsed = (
            min(_floor_seconds(effective - start), DURATION_LIMIT_SECONDS)
            if start
            else 0
        )
        remaining = max(0, DURATION_LIMIT_SECONDS - elapsed)
        ended_at = None
        is_expired = bool(expected and now >= expected)
    else:
        ended_at = duty.end_time
        if start and ended_at:
            elapsed = min(_floor_seconds(ended_at - start), DURATION_LIMIT_SECONDS)
        else:
            elapsed = 0
        remaining = 0
        is_expired = bool(
            duty.auto_ended or duty.completion_reason == COMPLETION_AUTO_EXPIRED
        )

    return {
        "id": duty.id,
        "status": duty_public_status(duty),
        "start_time": start.isoformat() if start else None,
        "started_at": start.isoformat() if start else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "end_time": ended_at.isoformat() if ended_at else None,
        "duration_limit_seconds": DURATION_LIMIT_SECONDS,
        "expected_end_at": expected.isoformat() if expected else None,
        "server_now": now.isoformat(),
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "is_expired": is_expired,
        "completion_reason": duty.completion_reason,
        "auto_ended": bool(duty.auto_ended),
        "is_active": bool(duty.is_active),
    }


def empty_duty_timer(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or timezone.now()
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
    }
