"""Shared fixtures for attendance tests."""

from __future__ import annotations

from django.contrib.auth.models import User

from accounts.models import EmployeeProfile
from attendance.devices import issue_device
from attendance.models import (
    AttendanceEmployee,
    EmployeeShopAssignment,
    Shift,
    Shop,
)

STRONG = "SecurePass1!"


def make_admin(username="att_admin") -> User:
    return User.objects.create_user(
        username=username, password=STRONG, is_staff=True, is_active=True
    )


def make_employee(
    employee_code="ATT-0001", full_name=None, is_active=True, **kwargs
) -> AttendanceEmployee:
    return AttendanceEmployee.objects.create(
        employee_code=employee_code,
        full_name=full_name or f"Test {employee_code}",
        is_active=is_active,
        **kwargs,
    )


def make_field_user(employee_id="KAC-0001", username=None):
    """A real Field Officer (Django user + EmployeeProfile)."""
    user = User.objects.create_user(
        username=username or employee_id.lower(),
        password=STRONG,
        is_staff=False,
        is_active=True,
        first_name="Field",
        last_name=employee_id,
    )
    profile = EmployeeProfile.objects.create(
        user=user, employee_id=employee_id, phone="9000000002", role="FieldAgent"
    )
    return user, profile


def make_shop(code="SHOP-01", name="Main Shop", **kwargs) -> Shop:
    return Shop.objects.create(code=code, name=name, **kwargs)


def make_shift(shop, name="Morning", start_time="09:00", end_time="18:00", **kwargs) -> Shift:
    return Shift.objects.create(
        shop=shop, name=name, start_time=start_time, end_time=end_time, **kwargs
    )


def admin_headers(testcase, username="att_admin"):
    """Authenticate an APITestCase client as a staff admin. Returns {} so
    callers can write client.post(url, data, format="json", **headers)."""
    testcase.client.force_authenticate(user=make_admin(username))
    return {}


def make_device(shop, device_uid="dev-001", name="Kiosk 1", registered_by=None):
    return issue_device(
        shop=shop,
        device_uid=device_uid,
        name=name,
        device_type="KIOSK",
        registered_by=registered_by,
    )


def make_assignment(employee, shop, **kwargs) -> EmployeeShopAssignment:
    return EmployeeShopAssignment.objects.create(
        employee=employee, shop=shop, **kwargs
    )


def device_headers(device_uid: str, token: str) -> dict:
    return {"HTTP_X_DEVICE_ID": device_uid, "HTTP_X_DEVICE_TOKEN": token}
