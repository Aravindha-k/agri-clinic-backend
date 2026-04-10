from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrOwner(BasePermission):
    """
    Custom permission: Admins can do anything. Employees can only access their own visits.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        return obj.employee == request.user

    def has_permission(self, request, view):
        # Allow all authenticated users to list/create
        return request.user and request.user.is_authenticated
