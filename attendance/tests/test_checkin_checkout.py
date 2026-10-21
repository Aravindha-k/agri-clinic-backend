"""Check-in/check-out flow: assignment, duplicates, idempotency, test labels."""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.models import (
    AttendanceAuditLog,
    AttendanceEvent,
    AttendanceDailySummary,
)
from attendance.tests.helpers import (
    device_headers,
    make_assignment,
    make_device,
    make_employee,
    make_shop,
)

CHECKIN_URL = "/api/v1/attendance/check-in/"
CHECKOUT_URL = "/api/v1/attendance/check-out/"
STATUS_URL = "/api/v1/attendance/status/"


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class CheckInOutFlowTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.other_shop = make_shop(code="SHOP-02", name="Other")
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.client = APIClient()
        self.headers = device_headers("dev-001", self.issued.plaintext_token)

    def check_in(self, employee=None, **extra):
        payload = {"employee_id": (employee or self.employee).id, **extra}
        return self.client.post(CHECKIN_URL, payload, **self.headers)

    def check_out(self, employee=None, **extra):
        payload = {"employee_id": (employee or self.employee).id, **extra}
        return self.client.post(CHECKOUT_URL, payload, **self.headers)

    def test_check_in_success(self):
        resp = self.check_in(client_event_id="evt-1")
        self.assertEqual(resp.status_code, 201)
        ev = resp.data["data"]["event"]
        self.assertEqual(ev["event_type"], "CHECK_IN")
        self.assertEqual(ev["verification_method"], "TEST_MANUAL")
        self.assertTrue(ev["is_test_mode"])
        self.assertEqual(ev["shop_code"], "SHOP-01")
        self.assertFalse(resp.data["data"]["idempotent_replay"])

    def test_checkout_after_checkin(self):
        self.check_in()
        resp = self.check_out()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["data"]["event"]["event_type"], "CHECK_OUT")

    def test_double_checkin_conflict(self):
        self.check_in()
        resp = self.check_in()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "OPEN_SESSION_EXISTS")

    def test_checkout_without_checkin_conflict(self):
        resp = self.check_out()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "NO_OPEN_SESSION")

    def test_idempotent_replay_same_client_event_id(self):
        r1 = self.check_in(client_event_id="dup-1")
        r2 = self.check_in(client_event_id="dup-1")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["data"]["idempotent_replay"])
        self.assertEqual(r1.data["data"]["event"]["id"], r2.data["data"]["event"]["id"])
        self.assertEqual(AttendanceEvent.objects.count(), 1)

    def test_client_event_id_reuse_for_different_event_conflicts(self):
        self.check_in(client_event_id="shared-1")
        resp = self.check_out(client_event_id="shared-1")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "IDEMPOTENCY_CONFLICT")

    def test_unassigned_employee_rejected(self):
        stranger = make_employee(employee_code="KAC-0099")
        resp = self.check_in(employee=stranger)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "NOT_ASSIGNED")

    def test_employee_assigned_elsewhere_rejected(self):
        stranger = make_employee(employee_code="KAC-0098")
        make_assignment(stranger, self.other_shop)
        resp = self.check_in(employee=stranger)
        self.assertEqual(resp.status_code, 409)

    def test_expired_assignment_window_rejected(self):
        emp = make_employee(employee_code="KAC-0097")
        make_assignment(
            emp, self.shop, valid_to=date.today() - timedelta(days=1)
        )
        resp = self.check_in(employee=emp)
        self.assertEqual(resp.status_code, 409)

    def test_inactive_assignment_rejected(self):
        emp = make_employee(employee_code="KAC-0096")
        make_assignment(emp, self.shop, is_active=False)
        resp = self.check_in(employee=emp)
        self.assertEqual(resp.status_code, 409)

    def test_unknown_employee_404(self):
        resp = self.client.post(
            CHECKIN_URL, {"employee_id": 999999}, **self.headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_shop_derived_from_device_not_client(self):
        # Even if the client claims another shop, the event is recorded on the
        # device's shop.
        resp = self.check_in(shop_id=self.other_shop.id)
        self.assertEqual(resp.status_code, 201)
        ev = AttendanceEvent.objects.get()
        self.assertEqual(ev.shop_id, self.shop.id)

    def test_client_cannot_claim_biometric(self):
        resp = self.check_in(verification_method="BIOMETRIC", is_test_mode=False)
        self.assertEqual(resp.status_code, 201)
        ev = AttendanceEvent.objects.get()
        self.assertEqual(ev.verification_method, "TEST_MANUAL")
        self.assertTrue(ev.is_test_mode)

    def test_server_timestamp_used(self):
        fake_past = "2020-01-01T00:00:00Z"
        self.check_in(occurred_at=fake_past)
        ev = AttendanceEvent.objects.get()
        self.assertGreater(
            ev.occurred_at, timezone.now() - timedelta(minutes=5)
        )

    def test_status_endpoint(self):
        resp = self.client.get(
            STATUS_URL, {"employee_id": self.employee.id}, **self.headers
        )
        self.assertFalse(resp.data["data"]["has_open_session"])
        self.check_in()
        resp = self.client.get(
            STATUS_URL, {"employee_id": self.employee.id}, **self.headers
        )
        self.assertTrue(resp.data["data"]["has_open_session"])

    def test_audit_log_written_for_events(self):
        self.check_in()
        self.check_out()
        actions = list(
            AttendanceAuditLog.objects.values_list("action", flat=True)
        )
        self.assertIn("CHECK_IN", actions)
        self.assertIn("CHECK_OUT", actions)

    def test_sequential_days_allowed(self):
        self.check_in()
        self.check_out()
        resp = self.check_in()
        self.assertEqual(resp.status_code, 201)


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class ConcurrencyTests(TestCase):
    """Race conditions: the assignment row lock serializes writers."""

    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.client = APIClient()
        self.headers = device_headers("dev-001", self.issued.plaintext_token)

    def test_locked_assignment_recheck_blocks_second_writer(self):
        """Simulate a lost update: if latest event flips between check and
        insert, the unique open-session rule still applies because the second
        writer re-reads under the same lock."""
        from attendance import services
        from attendance.biometrics import VerificationResult

        ver = VerificationResult(ok=True, method="TEST_MANUAL", is_test_mode=True)
        services.perform_event(
            employee=self.employee,
            shop=self.shop,
            device=self.issued.device,
            event_type="CHECK_IN",
            verification=ver,
        )
        with self.assertRaises(services.OpenSessionExists):
            services.perform_event(
                employee=self.employee,
                shop=self.shop,
                device=self.issued.device,
                event_type="CHECK_IN",
                verification=ver,
            )
        self.assertEqual(AttendanceEvent.objects.count(), 1)


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class OvernightShiftTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.client = APIClient()
        self.headers = device_headers("dev-001", self.issued.plaintext_token)

    def _post(self, url, when, **extra):
        with mock.patch(
            "attendance.services.timezone.now", return_value=when
        ):
            payload = {"employee_id": self.employee.id, **extra}
            return self.client.post(url, payload, **self.headers)

    def test_overnight_worked_time_attributed_to_checkin_date(self):
        in_at = timezone.now().replace(hour=22, minute=0) - timedelta(days=1)
        out_at = in_at + timedelta(hours=8)
        r1 = self._post(CHECKIN_URL, in_at)
        r2 = self._post(CHECKOUT_URL, out_at)
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        summary = AttendanceDailySummary.objects.get()
        self.assertEqual(summary.date, timezone.localtime(in_at).date())
        self.assertEqual(summary.worked_seconds, 8 * 3600)
        self.assertEqual(summary.status, "PRESENT")
        self.assertTrue(summary.contains_test_events)

    def test_open_session_marks_incomplete(self):
        self._post(CHECKIN_URL, timezone.now())
        summary = AttendanceDailySummary.objects.get()
        self.assertEqual(summary.status, "INCOMPLETE")
        self.assertTrue(summary.has_open_session)

    def test_night_shift_matched(self):
        from attendance.models import Shift

        Shift.objects.create(
            shop=self.shop,
            name="Night",
            start_time="20:00",
            end_time="06:00",
        )
        in_at = timezone.now().replace(hour=23, minute=30)
        self._post(CHECKIN_URL, in_at)
        ev = AttendanceEvent.objects.get()
        self.assertEqual(ev.shift.name, "Night")

    def test_checkout_inherits_checkin_shift(self):
        from attendance.models import Shift

        Shift.objects.create(
            shop=self.shop,
            name="Night",
            start_time="20:00",
            end_time="06:00",
        )
        in_at = timezone.now().replace(hour=22, minute=0) - timedelta(days=1)
        self._post(CHECKIN_URL, in_at)
        self._post(CHECKOUT_URL, in_at + timedelta(hours=8))
        out_ev = AttendanceEvent.objects.get(event_type="CHECK_OUT")
        self.assertEqual(out_ev.shift.name, "Night")
