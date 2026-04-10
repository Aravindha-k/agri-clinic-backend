"""
accounts/selectors.py
─────────────────────
Pure read / query functions for the accounts/employees domain.
No business logic lives here – only filtered querysets and lookups.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.contrib.auth.models import User
from django.db.models import QuerySet, Prefetch

from .models import EmployeeProfile

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# User lookups
# ──────────────────────────────────────────────────────────────


def get_user_by_id(user_id: int) -> Optional[User]:
    """Return a User or None."""
    return User.objects.select_related("employee_profile").filter(pk=user_id).first()


def get_user_by_username(username: str) -> Optional[User]:
    return (
        User.objects.select_related("employee_profile")
        .filter(username=username)
        .first()
    )


def get_user_by_employee_id(employee_id: str) -> Optional[User]:
    profile = (
        EmployeeProfile.objects.select_related("user")
        .filter(employee_id=employee_id)
        .first()
    )
    return profile.user if profile else None


# ──────────────────────────────────────────────────────────────
# Employee profile queries
# ──────────────────────────────────────────────────────────────


def get_all_employees(
    *,
    is_active: Optional[bool] = None,
    role: Optional[str] = None,
    district_id: Optional[int] = None,
    search: Optional[str] = None,
) -> QuerySet:
    """
    Return a filtered, ordered queryset of EmployeeProfile objects.

    All parameters are optional keyword-only arguments so call sites
    are always explicit.
    """
    qs = EmployeeProfile.objects.select_related("user", "district", "village").order_by(
        "employee_id"
    )

    if is_active is not None:
        qs = qs.filter(is_active_employee=is_active)

    if role:
        qs = qs.filter(role=role)

    if district_id:
        qs = qs.filter(district_id=district_id)

    if search:
        qs = (
            qs.filter(user__username__icontains=search)
            | qs.filter(employee_id__icontains=search)
            | qs.filter(phone__icontains=search)
        )

    return qs


def get_employee_profile(user: User) -> Optional[EmployeeProfile]:
    return (
        EmployeeProfile.objects.select_related("user", "district", "village")
        .filter(user=user)
        .first()
    )


def get_employee_by_id(employee_id: str) -> Optional[EmployeeProfile]:
    return (
        EmployeeProfile.objects.select_related("user", "district", "village")
        .filter(employee_id=employee_id)
        .first()
    )


def get_active_employee_count() -> int:
    return EmployeeProfile.objects.filter(is_active_employee=True).count()
