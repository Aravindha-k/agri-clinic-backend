"""Guards for Admin Panel mutations against owner / superuser accounts."""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied


def assert_can_mutate_employee_account(*, actor, target_user) -> None:
    """
    Non-superuser staff must not modify/deactivate/delete owner (superuser) accounts.

    Superusers may manage other staff/admins (existing product behavior).
    """
    if target_user is None:
        return
    if getattr(target_user, "is_superuser", False) and not getattr(
        actor, "is_superuser", False
    ):
        raise PermissionDenied(
            "You cannot modify or deactivate the owner (superuser) account."
        )
