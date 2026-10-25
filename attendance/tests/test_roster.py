"""Device-scoped roster: GET /api/v1/attendance/roster/ (security + contract)."""

from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from attendance.devices import revoke_device
from attendance.models import (
    AttendanceEmployee,
    AttendanceEvent,
    EmployeeShopAssignment,
    FaceEnrollment,
)
from attendance.tests.helpers import (
    device_headers,
    make_assignment,
    make_device,
    make_employee,
    make_shop,
)

ROSTER_URL = "/api/v1/attendance/roster/"


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=False)
class DeviceRosterTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.device = self.issued.device
        self.headers = device_headers(
            self.device.device_uid, self.issued.plaintext_token
        )
        self.kavya = make_employee("EMP-0001", "Kavya", phone="9000000001")
        make_assignment(self.kavya, self.shop)

    def _enroll(self, employee, status, device=None):
        return FaceEnrollment.objects.create(
            employee=employee, shop=self.shop, device=device or self.device,
            status=status, consent_recorded=True, consent_at=timezone.now(),
        )

    def _get(self, **headers):
        return self.client.get(ROSTER_URL, **(headers or self.headers))

    def _rows(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["data"]["employees"]

    # ── security ──────────────────────────────────────────────────
    def test_requires_device_credentials(self):
        resp = self.client.get(ROSTER_URL)
        self.assertIn(resp.status_code, (401, 403))
        self.assertNotIn(b"Kavya", resp.content)

    def test_wrong_token_rejected(self):
        resp = self.client.get(
            ROSTER_URL, **device_headers(self.device.device_uid, "wrong-token")
        )
        self.assertIn(resp.status_code, (401, 403))
        self.assertNotIn(b"Kavya", resp.content)

    def test_revoked_device_rejected(self):
        revoke_device(self.device)
        resp = self._get()
        self.assertIn(resp.status_code, (401, 403))
        self.assertNotIn(b"Kavya", resp.content)

    def test_works_with_test_mode_disabled(self):
        self.assertEqual(self._get().status_code, 200)

    def test_only_own_shop_employees(self):
        other_shop = make_shop(code="SHOP-02", name="Other Shop")
        outsider = make_employee("EMP-0099", "Outsider")
        make_assignment(outsider, other_shop)
        codes = [r["employee_code"] for r in self._rows()]
        self.assertEqual(codes, ["EMP-0001"])

    def test_client_supplied_shop_is_ignored(self):
        other_shop = make_shop(code="SHOP-02", name="Other Shop")
        outsider = make_employee("EMP-0099", "Outsider")
        make_assignment(outsider, other_shop)
        resp = self.client.get(
            ROSTER_URL, {"shop_id": other_shop.id, "shop": other_shop.code},
            **self.headers,
        )
        codes = [r["employee_code"] for r in resp.data["data"]["employees"]]
        self.assertEqual(codes, ["EMP-0001"])
        self.assertEqual(resp.data["data"]["shop"]["code"], self.shop.code)

    def test_inactive_employee_and_assignment_excluded(self):
        gone = make_employee("EMP-0002", "Inactive", is_active=False)
        make_assignment(gone, self.shop)
        moved = make_employee("EMP-0003", "Moved")
        make_assignment(moved, self.shop, is_active=False)
        future = make_employee("EMP-0004", "Future")
        make_assignment(
            future, self.shop,
            valid_from=timezone.localdate() + datetime.timedelta(days=3),
        )
        ended = make_employee("EMP-0005", "Ended")
        make_assignment(
            ended, self.shop,
            valid_to=timezone.localdate() - datetime.timedelta(days=1),
        )
        self.assertEqual([r["employee_code"] for r in self._rows()], ["EMP-0001"])

    def test_no_phone_or_biometric_fields(self):
        resp = self._get()
        body = resp.content.decode().lower()
        self.assertNotIn("9000000001", body)
        for word in ("phone", "embedding", "template", "image", "token"):
            self.assertNotIn(word, body)
        self.assertEqual(
            set(resp.data["data"]["employees"][0]),
            {"employee_id", "employee_code", "employee_name",
             "enrollment_status", "enrollment_id"},
        )

    # ── contract / statuses ──────────────────────────────────────
    def test_contract_shape(self):
        data = self._get().data["data"]
        self.assertEqual(data["shop"], {"code": self.shop.code, "name": self.shop.name})
        self.assertEqual(data["employees"][0], {
            "employee_id": self.kavya.id,
            "employee_code": "EMP-0001",
            "employee_name": "Kavya",
            "enrollment_status": "NOT_AUTHORIZED",
            "enrollment_id": None,
        })
        self.assertEqual(data["summary"], {"assigned": 1, "authorized": 0, "enrolled": 0})

    def test_pending_and_active_statuses(self):
        pending = self._enroll(self.kavya, FaceEnrollment.STATUS_PENDING)
        raj = make_employee("EMP-0002", "Raj")
        make_assignment(raj, self.shop)
        active = self._enroll(raj, FaceEnrollment.STATUS_ACTIVE)
        data = self._get().data["data"]
        by_code = {r["employee_code"]: r for r in data["employees"]}
        self.assertEqual(by_code["EMP-0001"]["enrollment_status"], "PENDING")
        self.assertEqual(by_code["EMP-0001"]["enrollment_id"], pending.id)
        self.assertEqual(by_code["EMP-0002"]["enrollment_status"], "ACTIVE")
        self.assertEqual(by_code["EMP-0002"]["enrollment_id"], active.id)
        self.assertEqual(data["summary"], {"assigned": 2, "authorized": 2, "enrolled": 1})

    def test_authorization_for_other_device_is_not_authorized_here(self):
        other = make_device(self.shop, device_uid="dev-002")
        self._enroll(self.kavya, FaceEnrollment.STATUS_PENDING, device=other.device)
        row = self._rows()[0]
        self.assertEqual(row["enrollment_status"], "NOT_AUTHORIZED")
        self.assertIsNone(row["enrollment_id"])

    def test_revoked_or_replaced_authorization_is_not_authorized(self):
        self._enroll(self.kavya, FaceEnrollment.STATUS_REVOKED)
        self.assertEqual(self._rows()[0]["enrollment_status"], "NOT_AUTHORIZED")

    def test_roster_enrollment_id_matches_enrollments_endpoint(self):
        pending = self._enroll(self.kavya, FaceEnrollment.STATUS_PENDING)
        enrollments = self.client.get(
            "/api/v1/attendance/enrollments/", **self.headers
        ).data["data"]["enrollments"]
        self.assertEqual(enrollments[0]["enrollment_id"], pending.id)
        self.assertEqual(self._rows()[0]["enrollment_id"], pending.id)

    def test_read_only(self):
        before = (
            AttendanceEmployee.objects.count(),
            EmployeeShopAssignment.objects.count(),
            FaceEnrollment.objects.count(),
            AttendanceEvent.objects.count(),
        )
        self._get()
        for method in (self.client.post, self.client.put,
                       self.client.patch, self.client.delete):
            self.assertEqual(method(ROSTER_URL, {}, **self.headers).status_code, 405)
        after = (
            AttendanceEmployee.objects.count(),
            EmployeeShopAssignment.objects.count(),
            FaceEnrollment.objects.count(),
            AttendanceEvent.objects.count(),
        )
        self.assertEqual(before, after)
