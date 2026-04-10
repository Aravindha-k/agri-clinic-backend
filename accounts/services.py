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
from django.db import IntegrityError, transaction

from rest_framework_simplejwt.tokens import RefreshToken

from .models import EmployeeProfile
from .utils import generate_employee_id

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
    username: str,
    password: str,
    phone: str,
    role: str = "FieldAgent",
    district_id: Optional[int] = None,
    village_id: Optional[int] = None,
    created_by: Optional[User] = None,
) -> EmployeeProfile:
    """
    Create a Django user + EmployeeProfile in a single transaction.
    """
    if User.objects.filter(username=username).exists():
        raise EmployeeServiceError(f"Username '{username}' is already taken.")

    if EmployeeProfile.objects.filter(
        user__employee_profile__phone=phone  # noqa: F821
    ).exists():
        pass  # Phone uniqueness is not enforced at DB level; proceed.

    employee_id = generate_employee_id()

    user = User.objects.create_user(
        username=username,
        password=password,
        is_staff=False,
        is_active=True,
    )

    profile = EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone=phone,
        role=role,
        district_id=district_id,
        village_id=village_id,
        is_active_employee=True,
        can_login=True,
    )

    logger.info(
        "Employee created: %s (%s) by user_id=%s",
        employee_id,
        username,
        created_by.pk if created_by else "system",
    )
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
    """Flip the is_active_employee flag."""
    profile.is_active_employee = not profile.is_active_employee
    profile.can_login = profile.is_active_employee
    profile.save(update_fields=["is_active_employee", "can_login"])
    logger.info(
        "Employee %s toggled active=%s",
        profile.employee_id,
        profile.is_active_employee,
    )
    return profile


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
