"""Owner-only security/system/audit endpoint authorization."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import EmployeeProfile


STRONG_PASSWORD = "SecurePass1!"


def _auth_client(user: User) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def _make_owner():
    user = User.objects.create_user(
        username="owner.sec.test",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=True,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="OWN-SEC",
        phone="9000000101",
        is_active_employee=True,
        can_login=True,
    )
    return user


def _make_staff_admin():
    user = User.objects.create_user(
        username="staff.sec.test",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="ADM-SEC",
        phone="9000000102",
        is_active_employee=True,
        can_login=True,
        role="admin",
    )
    return user


class OwnerOnlySecurityEndpointsTests(TestCase):
    def setUp(self):
        self.owner = _make_owner()
        self.staff = _make_staff_admin()
        self.owner_client = _auth_client(self.owner)
        self.staff_client = _auth_client(self.staff)
        self.anon = APIClient()

    def test_security_monitoring_owner_ok_staff_forbidden(self):
        url = "/api/v1/employees/admin/security/"
        self.assertEqual(self.owner_client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.staff_client.get(url).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(self.anon.get(url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_audit_logs_owner_ok_staff_forbidden(self):
        url = "/api/v1/audit/logs/"
        self.assertEqual(self.owner_client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.staff_client.get(url).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(self.anon.get(url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_system_settings_owner_only(self):
        url = "/api/v1/system/settings/"
        self.assertEqual(self.owner_client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.staff_client.get(url).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.staff_client.patch(
                url, {"key": "x", "value": "y"}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.anon.get(url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_system_config_staff_can_get_not_put(self):
        url = "/api/v1/system/config/"
        self.assertEqual(self.staff_client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.owner_client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.staff_client.put(
                url, {"heartbeat_timeout_minutes": 42}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        put_owner = self.owner_client.put(
            url, {"heartbeat_timeout_minutes": 42}, format="json"
        )
        self.assertEqual(put_owner.status_code, status.HTTP_200_OK)

    def test_create_admin_owner_only(self):
        url = "/api/v1/employees/create-admin/"
        payload = {
            "username": "new.staff.from.owner",
            "password": STRONG_PASSWORD,
            "phone": "9000000199",
        }
        self.assertEqual(
            self.staff_client.post(url, payload, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.owner_client.post(url, payload, format="json").status_code,
            status.HTTP_201_CREATED,
        )

    def test_dev_reset_staff_forbidden(self):
        url = "/api/v1/admin/dev/reset-test-data/"
        self.assertEqual(
            self.staff_client.post(url, {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_staff_still_can_operational_farmer_list(self):
        """Regression: owner-only tightening must not block normal admin CRUD."""
        r = self.staff_client.get("/api/v1/admin/farmers/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
