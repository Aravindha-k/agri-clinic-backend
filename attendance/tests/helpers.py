"""Shared fixtures for attendance tests."""

from __future__ import annotations

from django.contrib.auth.models import User

from accounts.models import EmployeeProfile
from attendance.devices import issue_device
from attendance.models import EmployeeShopAssignment, Shop

STRONG = "SecurePass1!"


def make_admin(username="att_admin") -> User:
    return User.objects.create_user(
        username=username, password=STRONG, is_staff=True, is_active=True
    )


def make_employee(employee_id="KAC-0001", username=None) -> EmployeeProfile:
    user = User.objects.create_user(
        username=username or employee_id.lower(),
        password=STRONG,
        is_staff=False,
        is_active=True,
        first_name="Test",
        last_name=employee_id,
    )
    return EmployeeProfile.objects.create(
        user=user, employee_id=employee_id, phone="9000000002", role="FieldAgent"
    )


def make_shop(code="SHOP-01", name="Main Shop") -> Shop:
    return Shop.objects.create(code=code, name=name)


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
