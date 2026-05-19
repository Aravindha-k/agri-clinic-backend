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


def employee_me_payload(request, profile: EmployeeProfile) -> dict:
    user = profile.user
    display_name = user.get_full_name() or user.username
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
        "role": profile.role,
        "is_active_employee": profile.is_active_employee,
        "can_login": user.is_active,
    }
    payload.update(employee_photo_fields(request, profile))
    return payload


def save_employee_profile_photo(profile: EmployeeProfile, file_obj) -> EmployeeProfile:
    if profile.profile_photo:
        profile.profile_photo.delete(save=False)
    profile.profile_photo = file_obj
    profile.profile_photo_updated_at = timezone.now()
    profile.save(update_fields=["profile_photo", "profile_photo_updated_at"])
    invalidate_employee_photo_caches()
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
