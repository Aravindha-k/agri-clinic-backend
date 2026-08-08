from rest_framework.permissions import BasePermission

from utils.permissions import IsStaffAdmin


class IsAdminUser(IsStaffAdmin):
    """Admin Panel access: any authenticated staff user (not superuser-only)."""

    pass
