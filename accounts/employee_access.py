"""Canonical field-employee authentication eligibility and deactivate/reactivate."""

from __future__ import annotations

import logging

from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.exceptions import APIException, PermissionDenied

from accounts.device_sessions import revoke_user_device_sessions
from accounts.models import EmployeeProfile

logger = logging.getLogger(__name__)

EMPLOYEE_INACTIVE_CODE = "EMPLOYEE_INACTIVE"
EMPLOYEE_INACTIVE_MESSAGE = (
    "Your account has been deactivated. Please contact your administrator."
)


class EmployeeInactive(APIException):
    """403 — deactivated field employee cannot use mobile APIs."""

    status_code = 403
    default_code = EMPLOYEE_INACTIVE_CODE
    default_detail = EMPLOYEE_INACTIVE_MESSAGE


def field_employee_may_authenticate(user: User | None) -> bool:
    """
    Canonical mobile auth rule for field employees.

    Requires:
    - authenticated User
    - not staff/superuser (mobile is for field employees)
    - User.is_active
    - EmployeeProfile.is_active_employee
    - EmployeeProfile.can_login
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return False
    if not user.is_active:
        return False
    profile = getattr(user, "employee_profile", None)
    if profile is None:
        return False
    return bool(profile.is_active_employee and profile.can_login)


def assert_field_employee_may_authenticate(user: User) -> None:
    """
    Raise EmployeeInactive when a field employee profile exists but is inactive.

    Staff/superuser and users without EmployeeProfile are left alone (other
    auth layers handle those cases). This matches the historical
    DeviceSessionRequiredMixin contract used by shared /api/v1/farmers APIs.
    """
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return
    profile = getattr(user, "employee_profile", None)
    if profile is None:
        return
    if field_employee_may_authenticate(user):
        return
    raise EmployeeInactive()


def blacklist_user_refresh_tokens(user: User) -> int:
    """Blacklist outstanding refresh tokens so they cannot be rotated."""
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except Exception:
        logger.warning(
            "token_blacklist unavailable; skip refresh blacklist user_id=%s",
            getattr(user, "pk", None),
        )
        return 0

    count = 0
    for outstanding in OutstandingToken.objects.filter(user_id=user.pk):
        _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
        if created:
            count += 1
    if count:
        logger.info(
            "Refresh tokens blacklisted user_id=%s count=%s",
            user.pk,
            count,
        )
    return count


@transaction.atomic
def set_field_employee_active(
    profile: EmployeeProfile,
    *,
    active: bool,
    reason: str = "admin_status_change",
) -> EmployeeProfile:
    """
    Activate or deactivate a field employee with aligned auth flags.

    Deactivate:
    - is_active_employee=False, can_login=False, User.is_active=False
    - revoke DeviceSessions
    - blacklist outstanding refresh tokens

    Activate:
    - restore the three flags to True (no staff/superuser elevation)

    Does not end DutySession (duty lifecycle is independent of device auth).
    """
    profile = EmployeeProfile.objects.select_related("user").select_for_update().get(
        pk=profile.pk
    )
    user = profile.user
    if user.is_superuser:
        # Owner protection is enforced by callers; refuse here as defense in depth.
        raise PermissionDenied(
            "Cannot change active status of a superuser account."
        )

    profile.is_active_employee = bool(active)
    profile.can_login = bool(active)
    user.is_active = bool(active)
    user.save(update_fields=["is_active"])
    profile.save(update_fields=["is_active_employee", "can_login"])

    if not active:
        revoked = revoke_user_device_sessions(user, reason=reason)
        blacklisted = blacklist_user_refresh_tokens(user)
        logger.info(
            "Employee deactivated employee_id=%s user_id=%s sessions_revoked=%s "
            "refresh_blacklisted=%s reason=%s",
            profile.employee_id,
            user.pk,
            revoked,
            blacklisted,
            reason,
        )
    else:
        logger.info(
            "Employee activated employee_id=%s user_id=%s reason=%s",
            profile.employee_id,
            user.pk,
            reason,
        )
    return profile


def toggle_field_employee_active(
    profile: EmployeeProfile,
    *,
    reason: str = "admin_toggle",
) -> EmployeeProfile:
    """Flip active status using the canonical activate/deactivate path."""
    return set_field_employee_active(
        profile,
        active=not bool(profile.is_active_employee),
        reason=reason,
    )
