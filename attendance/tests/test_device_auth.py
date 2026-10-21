"""Device credential issuance, authentication, revocation tests."""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from attendance.devices import (
    authenticate_device,
    hash_token,
    issue_device,
    revoke_device,
    rotate_device_token,
)
from attendance.models import AttendanceAuditLog, AttendanceDevice
from attendance.tests.helpers import (
    device_headers,
    make_admin,
    make_device,
    make_employee,
    make_shop,
)

EMPLOYEES_URL = "/api/v1/attendance/employees/"
CHECKIN_URL = "/api/v1/attendance/check-in/"


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class DeviceCredentialTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.admin = make_admin()

    def test_token_stored_hashed_only(self):
        issued = make_device(self.shop, registered_by=self.admin)
        device = issued.device
        self.assertNotEqual(device.token_hash, issued.plaintext_token)
        self.assertEqual(device.token_hash, hash_token(issued.plaintext_token))
        self.assertEqual(len(device.token_hash), 64)
        self.assertTrue(
            issued.plaintext_token.startswith(device.token_prefix)
        )

    def test_authenticate_device_success(self):
        issued = make_device(self.shop)
        found = authenticate_device("dev-001", issued.plaintext_token)
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, issued.device.pk)
        found.refresh_from_db()
        self.assertIsNotNone(found.last_seen_at)

    def test_authenticate_device_wrong_token(self):
        make_device(self.shop)
        self.assertIsNone(authenticate_device("dev-001", "wrong-token"))

    def test_authenticate_device_unknown_uid(self):
        self.assertIsNone(authenticate_device("no-such", "x" * 40))

    def test_revoked_device_cannot_authenticate(self):
        issued = make_device(self.shop)
        revoke_device(issued.device)
        self.assertIsNone(authenticate_device("dev-001", issued.plaintext_token))

    def test_device_on_inactive_shop_rejected(self):
        issued = make_device(self.shop)
        self.shop.is_active = False
        self.shop.save()
        self.assertIsNone(authenticate_device("dev-001", issued.plaintext_token))

    def test_rotate_token_invalidates_old(self):
        issued = make_device(self.shop)
        old = issued.plaintext_token
        new = rotate_device_token(issued.device)
        self.assertIsNone(authenticate_device("dev-001", old))
        self.assertIsNotNone(authenticate_device("dev-001", new))

    def test_missing_headers_rejected(self):
        resp = APIClient().get(EMPLOYEES_URL)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="AUTH_FAILED").exists()
        )

    def test_audit_log_does_not_store_token(self):
        APIClient().get(EMPLOYEES_URL, **device_headers("dev-001", "secret-token-x"))
        log = AttendanceAuditLog.objects.get(action="AUTH_FAILED")
        self.assertNotIn("secret-token-x", str(log.metadata))
        self.assertNotIn("secret-token-x", log.entity_id)


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class DeviceEndpointAuthTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        from attendance.tests.helpers import make_assignment

        make_assignment(self.employee, self.shop)
        self.client = APIClient()

    def test_valid_credentials_list_employees(self):
        resp = self.client.get(
            EMPLOYEES_URL,
            **device_headers("dev-001", self.issued.plaintext_token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]["employees"]), 1)
        self.assertEqual(resp.data["data"]["mode"], "TEST_MANUAL")

    def test_wrong_token_403(self):
        resp = self.client.get(EMPLOYEES_URL, **device_headers("dev-001", "bad"))
        self.assertEqual(resp.status_code, 403)

    def test_jwt_does_not_substitute_device_auth(self):
        admin = make_admin()
        self.client.force_authenticate(user=admin)
        resp = self.client.get(EMPLOYEES_URL)
        self.assertEqual(resp.status_code, 403)


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=False)
class TestModeGateTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        from attendance.tests.helpers import make_assignment

        make_assignment(self.employee, self.shop)
        self.client = APIClient()
        self.headers = device_headers("dev-001", self.issued.plaintext_token)

    def test_employee_list_blocked_when_test_mode_off(self):
        resp = self.client.get(EMPLOYEES_URL, **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_checkin_blocked_when_test_mode_off(self):
        resp = self.client.post(
            CHECKIN_URL, {"employee_id": self.employee.id}, **self.headers
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "TEST_MODE_DISABLED")
