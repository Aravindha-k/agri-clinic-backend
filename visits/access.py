"""Visit queryset scoping for employees vs admin/owner users."""

from django.shortcuts import get_object_or_404

from .models import Visit


def is_privileged_user(user) -> bool:
    """Staff, superuser, or elevated employee profile roles see all visits."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    profile = getattr(user, "employee_profile", None)
    role = (getattr(profile, "role", "") or "").lower()
    return role in {"admin", "superadmin", "super_admin", "manager", "owner"}


def visits_for_user(user):
    qs = Visit.objects.all()
    if not is_privileged_user(user):
        qs = qs.filter(employee=user)
    return qs


def get_visit_for_user(user, visit_id):
    """404 if visit missing or outside the user's scope (no cross-employee leakage)."""
    return get_object_or_404(visits_for_user(user), pk=visit_id)
