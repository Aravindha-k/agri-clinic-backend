"""Farmer access rules for employee-facing APIs."""

from visits.access import is_privileged_user
from visits.models import Visit


def farmer_photo_editable_by(user, farmer) -> bool:
    """Employee may update photo for farmers they created, are assigned to, or visited."""
    if is_privileged_user(user):
        return True
    if farmer.assigned_employee_id == user.id:
        return True
    if farmer.created_by_employee_id == user.id:
        return True
    return Visit.objects.filter(employee_id=user.id, farmer_id=farmer.id).exists()
