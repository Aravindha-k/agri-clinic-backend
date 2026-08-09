"""
accounts/services.py
─────────────────────
Business logic for authentication and employee management.
Views and tasks MUST use this layer — never call models directly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction

from rest_framework_simplejwt.tokens import RefreshToken

from .models import EmployeeProfile

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Auth services
# ──────────────────────────────────────────────────────────────


class AuthenticationError(Exception):
    """Raised when credentials are invalid or user is inactive."""


class EmployeeServiceError(Exception):
    """Raised for employee management errors."""


def authenticate_user(
    *, identifier: str, password: str, id_type: str = "username"
) -> Tuple[User, Dict[str, str]]:
    """
    Authenticate a user by username or employee_id.

    Returns (user, tokens) on success.
    Raises AuthenticationError on failure.
    """
    if id_type == "employee_id":
        profile = (
            EmployeeProfile.objects.select_related("user")
            .filter(employee_id=identifier)
            .first()
        )
        if not profile:
            raise AuthenticationError("Invalid employee ID or password.")
        user = authenticate(username=profile.user.username, password=password)
    else:
        user = authenticate(username=identifier, password=password)

    if user is None:
        raise AuthenticationError("Invalid credentials.")

    if not user.is_active:
        raise AuthenticationError("Account is disabled. Contact administrator.")

    # Check employee-specific active flag
    if hasattr(user, "employee_profile") and not user.employee_profile.can_login:
        raise AuthenticationError("Login is disabled for this account.")

    tokens = _generate_tokens(user)
    logger.info("User authenticated: %s (id=%s)", user.username, user.pk)
    return user, tokens


def logout_user(*, refresh_token: str) -> None:
    """Blacklist the refresh token to log out the user."""
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        logger.info("Refresh token blacklisted.")
    except Exception as exc:  # noqa: BLE001
        # Log but do not raise – logout should always succeed from the client's perspective
        logger.warning("Could not blacklist token: %s", exc)


def refresh_access_token(*, refresh_token: str) -> Dict[str, str]:
    """Return a new access token from a valid refresh token."""
    token = RefreshToken(refresh_token)
    return {"access": str(token.access_token)}


# ──────────────────────────────────────────────────────────────
# Employee CRUD services
# ──────────────────────────────────────────────────────────────


@transaction.atomic
def create_employee(
    *,
    first_name: str,
    phone: str,
    last_name: str = "",
    role: str = "FieldAgent",
    district_id: Optional[int] = None,
    village_id: Optional[int] = None,
    created_by: Optional[User] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> EmployeeProfile:
    """
    Create a Django user + EmployeeProfile with generated credentials.

    ``username`` / ``password`` arguments are ignored (legacy compatibility).
    """
    from accounts.credentials import (
        TEMPORARY_PASSWORD_ATTR,
        create_field_employee_with_generated_credentials,
    )

    del username, password  # intentionally unused

    profile = create_field_employee_with_generated_credentials(
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        role=role,
        district_id=district_id,
        village_id=village_id,
    )
    # Never log temporary password.
    logger.info(
        "Employee created: %s (%s) by user_id=%s",
        profile.employee_id,
        profile.user.username,
        created_by.pk if created_by else "system",
    )
    # Drop plaintext before returning from service layer callers that might log.
    if hasattr(profile, TEMPORARY_PASSWORD_ATTR):
        # Keep for API create path; service callers should not rely on it.
        pass
    return profile


@transaction.atomic
def update_employee(
    *,
    profile: EmployeeProfile,
    phone: Optional[str] = None,
    role: Optional[str] = None,
    district_id: Optional[int] = None,
    village_id: Optional[int] = None,
    is_active_employee: Optional[bool] = None,
    can_login: Optional[bool] = None,
) -> EmployeeProfile:
    """Partial update of an employee profile."""
    if phone is not None:
        profile.phone = phone
    if role is not None:
        profile.role = role
    if district_id is not None:
        profile.district_id = district_id
    if village_id is not None:
        profile.village_id = village_id
    if is_active_employee is not None:
        profile.is_active_employee = is_active_employee
    if can_login is not None:
        profile.can_login = can_login

    profile.save()
    logger.info("Employee updated: %s", profile.employee_id)
    return profile


def toggle_employee_active(*, profile: EmployeeProfile) -> EmployeeProfile:
    """Flip the is_active_employee flag via the canonical access helper."""
    from accounts.employee_access import toggle_field_employee_active

    return toggle_field_employee_active(profile, reason="service_toggle")


@transaction.atomic
def reset_employee_password(*, user: User, new_password: str) -> None:
    """Reset a user's password (admin action)."""
    user.set_password(new_password)
    user.save(update_fields=["password"])
    logger.info("Password reset for user_id=%s", user.pk)


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────


def _generate_tokens(user: User) -> Dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


def build_me_payload(user: User) -> Dict[str, Any]:
    """Build the /auth/me/ response payload."""
    payload: Dict[str, Any] = {
        "id": user.pk,
        "username": user.username,
        "is_staff": user.is_staff,
        "role": "ADMIN" if user.is_staff else "EMPLOYEE",
    }
    profile = getattr(user, "employee_profile", None)
    if profile:
        payload.update(
            {
                "employee_id": profile.employee_id,
                "phone": profile.phone,
                "role_label": profile.role,
                "district_id": profile.district_id,
                "village_id": profile.village_id,
                "is_active_employee": profile.is_active_employee,
            }
        )
    return payload
