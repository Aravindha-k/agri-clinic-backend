"""
utils/permissions.py
─────────────────────
Reusable DRF permission classes for role-based access control.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsStaffAdmin(BasePermission):
    """
    Authenticated Django staff user (is_staff=True).

    Covers both:
    - owner / superuser (is_staff + is_superuser)
    - operational admin (is_staff, not necessarily superuser)

    Does NOT require is_superuser.
    """

    message = "Admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_staff
        )


# Backward-compatible aliases
IsAdmin = IsStaffAdmin
IsAdminUser = IsStaffAdmin


class IsSuperuserOnly(BasePermission):
    """Owner / superuser-only actions (create admin users, etc.)."""

    message = "Super Admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )


class IsEmployee(BasePermission):
    """Active, authenticated employees."""

    message = "Active employee account required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        profile = getattr(request.user, "employee_profile", None)
        if profile:
            return profile.is_active_employee and profile.can_login
        # Staff users always pass
        return request.user.is_staff


class IsAdminOrReadOnly(BasePermission):
    """
    Admin → full access.
    Any authenticated user → read-only (GET, HEAD, OPTIONS).
    """

    message = "Write access requires admin privileges."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_staff


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level: only the owner (employee who created it) or an admin.
    The view must set `owner_field` attribute (default: 'employee').
    """

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        owner_field = getattr(view, "owner_field", "employee")
        owner = getattr(obj, owner_field, None)
        return owner == request.user
