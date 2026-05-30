"""Single active mobile device session per employee."""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import Any

from django.contrib.auth.models import User
from django.utils import timezone

from .models import EmployeeDeviceSession, EmployeeProfile

logger = logging.getLogger(__name__)

DEVICE_SESSION_HEADER = "X-Device-Session"


class SessionCheckResult(str, Enum):
    OK = "ok"
    REPLACED = "replaced"
    MISSING = "missing"


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


def _resolve_active_device_id(data: dict | None) -> str:
    data = data or {}
    raw = (
        data.get("active_device_id")
        or data.get("device_id")
        or data.get("deviceId")
        or ""
    )
    if raw:
        return str(raw).strip()[:64]
    return str(uuid.uuid4())[:64]


def register_device_session(
    user: User, *, request_data: dict | None = None
) -> EmployeeDeviceSession:
    """Latest login wins: deactivate other sessions, bump session_version."""
    now = timezone.now()
    info = _parse_device_info(request_data)
    device_id = _resolve_active_device_id(request_data)

    profile = EmployeeProfile.objects.filter(user=user).first()
    if profile:
        profile.mobile_session_version = (profile.mobile_session_version or 0) + 1
        profile.active_device_id = device_id
        profile.save(update_fields=["mobile_session_version", "active_device_id"])
        session_version = profile.mobile_session_version
    else:
        session_version = 1

    EmployeeDeviceSession.objects.filter(user=user, is_active=True).update(
        is_active=False, updated_at=now
    )

    session = EmployeeDeviceSession.objects.create(
        user=user,
        session_key=uuid.uuid4(),
        active_device_id=device_id,
        session_version=session_version,
        is_active=True,
        last_login_at=now,
        last_seen_at=now,
        **info,
    )
    logger.info(
        "DeviceSession registered user_id=%s session_id=%s version=%s device_id=%s",
        user.pk,
        session.session_key,
        session_version,
        device_id,
    )
    return session


def touch_device_session(session: EmployeeDeviceSession) -> None:
    session.last_seen_at = timezone.now()
    session.save(update_fields=["last_seen_at", "updated_at"])


def check_device_session(user: User, session_id: str | None) -> SessionCheckResult:
    """Validate X-Device-Session header against the single active session."""
    active = get_active_device_session(user)

    if not session_id:
        return SessionCheckResult.REPLACED if active else SessionCheckResult.MISSING

    try:
        session_uuid = uuid.UUID(str(session_id).strip())
    except (TypeError, ValueError):
        return SessionCheckResult.REPLACED

    if active and active.session_key == session_uuid:
        touch_device_session(active)
        return SessionCheckResult.OK

    if EmployeeDeviceSession.objects.filter(
        user=user, session_key=session_uuid, is_active=False
    ).exists():
        logger.info(
            "DeviceSession replaced user_id=%s session_id=%s reason=superseded",
            user.pk,
            session_uuid,
        )
        return SessionCheckResult.REPLACED

    if active:
        logger.info(
            "DeviceSession replaced user_id=%s session_id=%s reason=another_device_active",
            user.pk,
            session_uuid,
        )
        return SessionCheckResult.REPLACED

    return SessionCheckResult.MISSING


def validate_device_session(user: User, session_id: str | None) -> EmployeeDeviceSession | None:
    """Backward-compatible: return session only when check is OK."""
    if check_device_session(user, session_id) == SessionCheckResult.OK:
        return get_active_device_session(user)
    return None


def get_active_device_session(user: User) -> EmployeeDeviceSession | None:
    return (
        EmployeeDeviceSession.objects.filter(user=user, is_active=True)
        .order_by("-last_login_at")
        .first()
    )


def _iso(dt) -> str | None:
    if not dt:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def active_device_payload(user: User) -> dict[str, Any]:
    """Active device block for mobile /me and admin."""
    profile = getattr(user, "employee_profile", None)
    session = get_active_device_session(user)
    return {
        "active_device_id": profile.active_device_id if profile else None,
        "session_version": profile.mobile_session_version if profile else 0,
        "device_session_id": str(session.session_key) if session else None,
        "device_name": session.device_name if session else None,
        "device_model": session.device_model if session else None,
        "platform": session.platform if session else None,
        "app_version": session.app_version if session else None,
        "last_login_at": _iso(session.last_login_at) if session else None,
        "last_seen_at": _iso(session.last_seen_at) if session else None,
        "is_active": bool(session),
    }


def batch_device_status_map(user_ids: list[int]) -> dict[int, dict[str, Any]]:
    """One query for active sessions; avoids N+1 on admin tracking lists."""
    if not user_ids:
        return {}
    sessions = {
        s.user_id: s
        for s in EmployeeDeviceSession.objects.filter(
            user_id__in=user_ids, is_active=True
        ).order_by("user_id", "-last_login_at")
    }
    result: dict[int, dict[str, Any]] = {}
    for uid in user_ids:
        session = sessions.get(uid)
        if session:
            result[uid] = {
                "active_device_id": session.active_device_id,
                "session_version": session.session_version,
                "device_name": session.device_name,
                "device_model": session.device_model,
                "platform": session.platform,
                "app_version": session.app_version,
                "last_login_at": _iso(session.last_login_at),
                "last_seen_at": _iso(session.last_seen_at),
                "is_active": True,
            }
        else:
            result[uid] = {
                "active_device_id": None,
                "session_version": 0,
                "device_name": None,
                "device_model": None,
                "platform": None,
                "app_version": None,
                "last_login_at": None,
                "last_seen_at": None,
                "is_active": False,
            }
    return result


def device_status_payload(user: User) -> dict[str, Any]:
    """Admin employee list device_status field."""
    session = get_active_device_session(user)
    if session:
        return {
            "active_device_id": session.active_device_id,
            "session_version": session.session_version,
            "device_name": session.device_name,
            "device_model": session.device_model,
            "platform": session.platform,
            "app_version": session.app_version,
            "last_login_at": _iso(session.last_login_at),
            "last_seen_at": _iso(session.last_seen_at),
            "is_active": True,
        }

    last_session = (
        EmployeeDeviceSession.objects.filter(user=user)
        .order_by("-last_login_at")
        .first()
    )
    if last_session:
        return {
            "active_device_id": last_session.active_device_id,
            "session_version": last_session.session_version,
            "device_name": last_session.device_name,
            "device_model": last_session.device_model,
            "platform": last_session.platform,
            "app_version": last_session.app_version,
            "last_login_at": _iso(last_session.last_login_at),
            "last_seen_at": _iso(last_session.last_seen_at),
            "is_active": False,
        }

    profile = getattr(user, "employee_profile", None)
    return {
        "active_device_id": profile.active_device_id if profile else None,
        "session_version": profile.mobile_session_version if profile else 0,
        "device_name": None,
        "device_model": None,
        "platform": None,
        "app_version": None,
        "last_login_at": None,
        "last_seen_at": None,
        "is_active": False,
    }
