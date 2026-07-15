"""Shared employee profile photo serialization and cache invalidation."""

from __future__ import annotations

import logging

from django.utils import timezone

from accounts.models import EmployeeProfile

logger = logging.getLogger(__name__)


def build_profile_photo_url(request, image_field) -> str | None:
    from utils.photo_urls import build_profile_photo_url as _build

    return _build(request, image_field)


def employee_photo_fields(request, profile: EmployeeProfile) -> dict:
    """Canonical profile_photo_url + updated_at for all API consumers."""
    updated_at = profile.profile_photo_updated_at
    url = build_profile_photo_url(request, profile.profile_photo)
    return {
        "profile_photo_url": url,
        "profile_photo_updated_at": (
            updated_at.isoformat() if updated_at else None
        ),
    }


def _workday_status_for_user(user) -> dict:
    from tracking.duty_service import serialize_duty_status
    from tracking.duty_timer import empty_duty_timer

    # Lazy expiry + canonical timer via serialize_duty_status
    payload = serialize_duty_status(user)
    if payload.get("is_active"):
        return {
            "status": "working",
            "is_active": True,
            "workday_id": payload.get("workday_id"),
            "duty_session_id": payload.get("duty_session_id"),
            "start_time": payload.get("start_time"),
            "started_at": payload.get("started_at"),
            "ends_at": payload.get("expected_end_at"),
            "expected_end_at": payload.get("expected_end_at"),
            "server_now": payload.get("server_now"),
            "elapsed_seconds": payload.get("elapsed_seconds"),
            "remaining_seconds": payload.get("remaining_seconds"),
            "duration_limit_seconds": payload.get("duration_limit_seconds"),
            "is_expired": payload.get("is_expired"),
            "completion_reason": payload.get("completion_reason"),
            "auto_ended": False,
            "duty_status": payload.get("duty_status"),
        }
    if payload.get("is_expired") or payload.get("completion_reason") == "AUTO_EXPIRED":
        return {
            "status": "auto_ended",
            "is_active": False,
            "workday_id": payload.get("workday_id"),
            "duty_session_id": payload.get("duty_session_id"),
            "start_time": payload.get("start_time"),
            "started_at": payload.get("started_at"),
            "ends_at": payload.get("ended_at") or payload.get("expected_end_at"),
            "expected_end_at": payload.get("expected_end_at"),
            "server_now": payload.get("server_now"),
            "elapsed_seconds": payload.get("elapsed_seconds"),
            "remaining_seconds": payload.get("remaining_seconds"),
            "duration_limit_seconds": payload.get("duration_limit_seconds"),
            "is_expired": True,
            "completion_reason": payload.get("completion_reason"),
            "auto_ended": True,
            "duty_status": payload.get("duty_status"),
        }
    if payload.get("duty_session_id"):
        return {
            "status": "stopped",
            "is_active": False,
            "workday_id": payload.get("workday_id"),
            "duty_session_id": payload.get("duty_session_id"),
            "start_time": payload.get("start_time"),
            "started_at": payload.get("started_at"),
            "ends_at": payload.get("ended_at"),
            "expected_end_at": payload.get("expected_end_at"),
            "server_now": payload.get("server_now"),
            "elapsed_seconds": payload.get("elapsed_seconds"),
            "remaining_seconds": payload.get("remaining_seconds"),
            "duration_limit_seconds": payload.get("duration_limit_seconds"),
            "is_expired": payload.get("is_expired"),
            "completion_reason": payload.get("completion_reason"),
            "auto_ended": bool(payload.get("auto_ended")),
            "duty_status": payload.get("duty_status"),
        }
    empty = empty_duty_timer()
    return {
        "status": "stopped",
        "is_active": False,
        "workday_id": None,
        "duty_session_id": None,
        "start_time": None,
        "started_at": None,
        "ends_at": None,
        "expected_end_at": None,
        "server_now": empty["server_now"],
        "elapsed_seconds": empty["elapsed_seconds"],
        "remaining_seconds": empty["remaining_seconds"],
        "duration_limit_seconds": empty["duration_limit_seconds"],
        "is_expired": False,
        "completion_reason": None,
        "auto_ended": False,
        "duty_status": "NOT_STARTED",
    }


def employee_me_payload(request, profile: EmployeeProfile) -> dict:
    user = profile.user
    display_name = user.get_full_name() or user.username
    from accounts.device_sessions import active_device_payload, device_status_payload

    payload = {
        "id": user.id,
        "profile_id": profile.id,
        "user_id": user.id,
        "username": user.username,
        "name": display_name,
        "full_name": display_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "employee_id": profile.employee_id,
        "phone": profile.phone,
        "designation": profile.get_role_display(),
        "role": profile.role,
        "is_active_employee": profile.is_active_employee,
        "can_login": user.is_active,
        "workday_status": _workday_status_for_user(user),
        "active_device": active_device_payload(user),
        "device_status": device_status_payload(user),
    }
    payload.update(employee_photo_fields(request, profile))
    return payload


def save_employee_profile_photo(profile: EmployeeProfile, file_obj, *, actor=None, request=None) -> EmployeeProfile:
    if profile.profile_photo:
        profile.profile_photo.delete(save=False)
    profile.profile_photo = file_obj
    profile.profile_photo_updated_at = timezone.now()
    profile.save(update_fields=["profile_photo", "profile_photo_updated_at"])
    invalidate_employee_photo_caches()
    try:
        from audit_logs.utils import create_audit_log

        create_audit_log(
            actor=actor,
            module="EMPLOYEES",
            action="UPLOAD",
            object_id=profile.pk,
            description=f"Employee profile photo updated: {profile.employee_id}",
            request=request,
        )
    except Exception:
        logger.debug("Employee photo audit log skipped", exc_info=True)
    return profile


def invalidate_employee_photo_caches() -> None:
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception:
        logger.debug("Dashboard cache invalidation skipped", exc_info=True)

    try:
        from django.core.cache import cache

        for pattern in (
            "dashboard:stats",
            "dashboard:summary",
            "tracking:admin:*",
            "employees:list:*",
        ):
            cache.delete(pattern)
    except Exception:
        logger.debug("Generic cache delete skipped", exc_info=True)
