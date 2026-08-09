from rest_framework.permissions import BasePermission

from accounts.employee_access import field_employee_may_authenticate


class IsEmployeeUser(BasePermission):
    """Active field employees only (not staff; must be active + can_login)."""

    message = (
        "Your account has been deactivated. Please contact your administrator."
    )
    code = "EMPLOYEE_INACTIVE"

    def has_permission(self, request, view):
        return field_employee_may_authenticate(request.user)
