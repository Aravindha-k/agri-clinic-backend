"""Single active mobile device session per employee."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.contrib.auth.models import User
from django.utils import timezone

from .models import EmployeeDeviceSession

logger = logging.getLogger(__name__)

DEVICE_SESSION_HEADER = "X-Device-Session"


def _parse_device_info(data: dict | None) -> dict[str, str | None]:
    data = data or {}
    return {
        "device_name": (data.get("device_name") or data.get("deviceName") or "")[:120]
        or None,
        "device_model": (data.get("device_model") or data.get("deviceModel") or "")[:120]
        or None,
        "platform": (data.get("platform") or data.get("os") or "")[:40] or None,
        "app_version": (data.get("app_version") or data.get("appVersion") or "")[:40]
        or None,
    }


def register_device_session(user: User, *, request_data: dict | None = None) -> EmployeeDeviceSession:
    """
    Latest login wins: deactivate other sessions, create a new active session.
    """
    now = timezone.now()
    info = _parse_device_info(request_data)

    EmployeeDeviceSession.objects.filter(user=user, is_active=True).update(
        is_active=False, updated_at=now
    )

    session = EmployeeDeviceSession.objects.create(
        user=user,
        session_key=uuid.uuid4(),
        is_active=True,
        last_login_at=now,
        last_seen_at=now,
        **info,
    )
    logger.info(
        "DeviceSession registered user_id=%s session_id=%s platform=%s",
        user.pk,
        session.session_key,
        session.platform,
    )
    return session


def touch_device_session(session: EmployeeDeviceSession) -> None:
    session.last_seen_at = timezone.now()
    session.save(update_fields=["last_seen_at", "updated_at"])


def validate_device_session(user: User, session_id: str | None) -> EmployeeDeviceSession | None:
    """Return active session row or None if missing/invalid."""
    if not session_id:
        return None
    try:
        session_uuid = uuid.UUID(str(session_id).strip())
    except (TypeError, ValueError):
        return None

    session = (
        EmployeeDeviceSession.objects.filter(
            user=user,
            session_key=session_uuid,
            is_active=True,
        )
        .first()
    )
    if session:
        touch_device_session(session)
    return session


def get_active_device_session(user: User) -> EmployeeDeviceSession | None:
    return (
        EmployeeDeviceSession.objects.filter(user=user, is_active=True)
        .order_by("-last_login_at")
        .first()
    )


def device_status_payload(user: User) -> dict[str, Any]:
    """Admin/mobile status block for the employee's current device session."""
    session = get_active_device_session(user)
    if not session:
        return {
            "device_name": None,
            "device_model": None,
            "platform": None,
            "app_version": None,
            "last_login_at": None,
            "last_seen_at": None,
            "is_active": False,
        }
    return {
        "device_name": session.device_name,
        "device_model": session.device_model,
        "platform": session.platform,
        "app_version": session.app_version,
        "last_login_at": session.last_login_at.isoformat()
        if session.last_login_at
        else None,
        "last_seen_at": session.last_seen_at.isoformat() if session.last_seen_at else None,
        "is_active": session.is_active,
    }
