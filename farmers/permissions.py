from rest_framework.permissions import BasePermission


class IsEmployee(BasePermission):
    """
    Allow access only to non-staff authenticated users (field employees).
    Staff/admin users are denied so they cannot create field data.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and not request.user.is_staff
        )


class IsAdminOnly(BasePermission):
    """
    Allow access only to staff/admin users.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_staff
        )
