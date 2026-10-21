"""Admin CRUD, reporting isolation, audit log tests."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from attendance import services
from attendance.biometrics import VerificationResult
from attendance.models import AttendanceAuditLog, AttendanceDevice
from attendance.tests.helpers import (
    device_headers,
    make_admin,
    make_assignment,
    make_device,
    make_employee,
    make_field_user,
    make_shop,
)

BASE = "/api/v1/admin/attendance"
CHECKIN_URL = "/api/v1/attendance/check-in/"
CHECKOUT_URL = "/api/v1/attendance/check-out/"


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class AdminCrudTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.shop = make_shop()

    def test_non_admin_forbidden(self):
        field_user, _profile = make_field_user()
        c = APIClient()
        c.force_authenticate(user=field_user)
        self.assertEqual(c.get(f"{BASE}/shops/").status_code, 403)

    def test_anonymous_forbidden(self):
        self.assertIn(
            APIClient().get(f"{BASE}/shops/").status_code, {401, 403}
        )

    def test_shop_crud(self):
        resp = self.client.post(
            f"{BASE}/shops/", {"code": "SHOP-09", "name": "New"}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        shop_id = resp.data["id"] if "id" in resp.data else resp.data["data"]["id"]
        resp = self.client.patch(
            f"{BASE}/shops/{shop_id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200)

    def test_device_register_returns_token_once(self):
        resp = self.client.post(
            f"{BASE}/devices/",
            {"shop": self.shop.id, "device_uid": "d-1", "name": "K1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        token = resp.data["data"]["token"]
        self.assertTrue(token)
        device = AttendanceDevice.objects.get(device_uid="d-1")
        self.assertNotEqual(device.token_hash, token)
        # list/detail must never include the token
        listing = self.client.get(f"{BASE}/devices/")
        self.assertNotIn("token", listing.data["results"][0])
        self.assertIn("token_prefix", listing.data["results"][0])

    def test_device_revoke_blocks_kiosk(self):
        resp = self.client.post(
            f"{BASE}/devices/",
            {"shop": self.shop.id, "device_uid": "d-2", "name": "K2"},
            format="json",
        )
        token = resp.data["data"]["token"]
        dev_id = resp.data["data"]["device"]["id"]
        emp = make_employee()
        make_assignment(emp, self.shop)
        ok = APIClient().post(
            CHECKIN_URL,
            {"employee_id": emp.id},
            **device_headers("d-2", token),
        )
        self.assertEqual(ok.status_code, 201)
        self.client.post(f"{BASE}/devices/{dev_id}/revoke/")
        blocked = APIClient().post(
            CHECKOUT_URL,
            {"employee_id": emp.id},
            **device_headers("d-2", token),
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="DEVICE_REVOKED").exists()
        )

    def test_assignment_crud_and_audit(self):
        emp = make_employee()
        resp = self.client.post(
            f"{BASE}/assignments/",
            {"employee": emp.id, "shop": self.shop.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="ASSIGNMENT_SAVED").exists()
        )

    def test_assignment_unique_constraint(self):
        emp = make_employee()
        make_assignment(emp, self.shop)
        resp = self.client.post(
            f"{BASE}/assignments/",
            {"employee": emp.id, "shop": self.shop.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_shift_crud(self):
        resp = self.client.post(
            f"{BASE}/shifts/",
            {
                "shop": self.shop.id,
                "name": "Day",
                "start_time": "09:00",
                "end_time": "18:00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data["crosses_midnight"])


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class ReportingIsolationTests(TestCase):
    """TEST_MANUAL rows must never appear in verified reports by default."""

    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.kiosk = APIClient()
        self.headers = device_headers("dev-001", self.issued.plaintext_token)
        # one test-mode pair
        self.kiosk.post(CHECKIN_URL, {"employee_id": self.employee.id}, **self.headers)
        self.kiosk.post(CHECKOUT_URL, {"employee_id": self.employee.id}, **self.headers)
        # one simulated biometric-verified pair (service level)
        ver = VerificationResult(ok=True, method="BIOMETRIC", is_test_mode=False)
        services.perform_event(
            employee=self.employee,
            shop=self.shop,
            device=self.issued.device,
            event_type="CHECK_IN",
            verification=ver,
        )
        services.perform_event(
            employee=self.employee,
            shop=self.shop,
            device=self.issued.device,
            event_type="CHECK_OUT",
            verification=ver,
        )

    def test_events_report_excludes_test_by_default(self):
        resp = self.client.get(f"{BASE}/reports/events/")
        rows = resp.data["data"]["results"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["verification_method"] == "BIOMETRIC" for r in rows))

    def test_events_report_include_test(self):
        resp = self.client.get(f"{BASE}/reports/events/?include_test=true")
        self.assertEqual(len(resp.data["data"]["results"]), 4)

    def test_daily_report_excludes_test_summaries_by_default(self):
        # The day contains test events → conservative exclusion from verified.
        resp = self.client.get(f"{BASE}/reports/daily/")
        self.assertEqual(len(resp.data["data"]["results"]), 0)

    def test_daily_report_include_test(self):
        resp = self.client.get(f"{BASE}/reports/daily/?include_test=true")
        rows = resp.data["data"]["results"]
        self.assertEqual(len(rows), 1)  # same day merges into one summary
        self.assertTrue(rows[0]["contains_test_events"])

    def test_report_date_and_shop_filters(self):
        today = timezone.localdate().isoformat()
        resp = self.client.get(
            f"{BASE}/reports/daily/?date_from={today}&date_to={today}&shop_id={self.shop.id}&include_test=true"
        )
        self.assertEqual(len(resp.data["data"]["results"]), 1)
        resp = self.client.get(
            f"{BASE}/reports/daily/?date_from=1999-01-01&date_to=1999-01-02&include_test=true"
        )
        self.assertEqual(len(resp.data["data"]["results"]), 0)

    def test_audit_log_endpoint(self):
        resp = self.client.get(f"{BASE}/audit-logs/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data["data"]["results"]), 2)
