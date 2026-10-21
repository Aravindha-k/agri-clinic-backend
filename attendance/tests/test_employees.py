"""Attendance-only employee CRUD, deactivation, transfers, history."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from attendance.models import (
    AttendanceAuditLog,
    AttendanceEmployee,
    AttendanceEvent,
    EmployeeShopAssignment,
)
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
EMP_URL = f"{BASE}/employees/"
CHECKIN_URL = "/api/v1/attendance/check-in/"
EMPLOYEES_URL = "/api/v1/attendance/employees/"


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class EmployeeCrudTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.shop = make_shop()

    def test_create_employee_no_user_account(self):
        resp = self.client.post(
            EMP_URL,
            {"employee_code": "ATT-100", "full_name": "Ravi Kumar", "phone": "98765"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        emp = AttendanceEmployee.objects.get(employee_code="ATT-100")
        self.assertTrue(emp.is_active)
        self.assertIsNone(emp.linked_profile)
        # no Django user created for attendance employees
        self.assertFalse(User.objects.filter(username__icontains="ATT-100").exists())
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="EMPLOYEE_SAVED").exists()
        )

    def test_duplicate_code_rejected(self):
        make_employee(employee_code="ATT-101")
        resp = self.client.post(
            EMP_URL,
            {"employee_code": "ATT-101", "full_name": "Dup"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_and_retrieve(self):
        emp = make_employee(employee_code="ATT-102", phone="111")
        self.assertEqual(self.client.get(EMP_URL).status_code, 200)
        resp = self.client.get(f"{EMP_URL}{emp.id}/")
        self.assertEqual(resp.data["employee_code"], "ATT-102")

    def test_edit_employee(self):
        emp = make_employee(employee_code="ATT-103")
        resp = self.client.patch(
            f"{EMP_URL}{emp.id}/", {"full_name": "Renamed"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        emp.refresh_from_db()
        self.assertEqual(emp.full_name, "Renamed")
        self.assertEqual(emp.updated_by, self.admin)

    def test_delete_blocked(self):
        emp = make_employee(employee_code="ATT-104")
        resp = self.client.delete(f"{EMP_URL}{emp.id}/")
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(AttendanceEmployee.objects.filter(pk=emp.id).exists())

    def test_deactivate_and_activate(self):
        emp = make_employee(employee_code="ATT-105")
        resp = self.client.post(f"{EMP_URL}{emp.id}/deactivate/")
        self.assertEqual(resp.status_code, 200)
        emp.refresh_from_db()
        self.assertFalse(emp.is_active)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="EMPLOYEE_DEACTIVATED").exists()
        )
        self.client.post(f"{EMP_URL}{emp.id}/activate/")
        emp.refresh_from_db()
        self.assertTrue(emp.is_active)

    def test_non_admin_forbidden(self):
        field_user, _ = make_field_user()
        c = APIClient()
        c.force_authenticate(user=field_user)
        self.assertEqual(c.get(EMP_URL).status_code, 403)
        self.assertEqual(
            c.post(EMP_URL, {"employee_code": "X", "full_name": "Y"}, format="json").status_code,
            403,
        )

    def test_anonymous_forbidden(self):
        self.assertIn(APIClient().get(EMP_URL).status_code, {401, 403})


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class DeactivationEnforcementTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.kiosk = APIClient()
        self.headers = device_headers("dev-001", self.issued.plaintext_token)

    def test_deactivated_employee_cannot_check_in(self):
        self.admin_client.post(f"{EMP_URL}{self.employee.id}/deactivate/")
        resp = self.kiosk.post(
            CHECKIN_URL, {"employee_id": self.employee.id}, **self.headers
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "EMPLOYEE_INACTIVE")
        self.assertEqual(AttendanceEvent.objects.count(), 0)

    def test_deactivated_employee_hidden_from_selection(self):
        self.admin_client.post(f"{EMP_URL}{self.employee.id}/deactivate/")
        resp = self.kiosk.get(EMPLOYEES_URL, **self.headers)
        self.assertEqual(len(resp.data["data"]["employees"]), 0)

    def test_inactive_assignment_hidden(self):
        assignment = EmployeeShopAssignment.objects.get()
        assignment.is_active = False
        assignment.save()
        resp = self.kiosk.get(EMPLOYEES_URL, **self.headers)
        self.assertEqual(len(resp.data["data"]["employees"]), 0)


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class TransferAndHistoryTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.shop_a = make_shop(code="SHOP-A", name="A")
        self.shop_b = make_shop(code="SHOP-B", name="B")
        self.issued_a = make_device(self.shop_a, device_uid="dev-a")
        self.employee = make_employee()
        self.assignment = make_assignment(self.employee, self.shop_a)
        self.kiosk = APIClient()
        self.headers_a = device_headers("dev-a", self.issued_a.plaintext_token)

    def test_transfer_assignment_to_other_shop(self):
        # record history at shop A first
        self.kiosk.post(
            CHECKIN_URL, {"employee_id": self.employee.id}, **self.headers_a
        )
        self.kiosk.post(
            "/api/v1/attendance/check-out/",
            {"employee_id": self.employee.id},
            **self.headers_a,
        )
        resp = self.client.patch(
            f"{BASE}/assignments/{self.assignment.id}/",
            {"shop": self.shop_b.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(
                action="EMPLOYEE_TRANSFERRED"
            ).exists()
        )
        # historical events remain attributed to shop A
        ev = AttendanceEvent.objects.filter(
            event_type="CHECK_IN"
        ).first()
        self.assertEqual(ev.shop_id, self.shop_a.id)
        # employee no longer selectable at shop A
        resp = self.kiosk.get(EMPLOYEES_URL, **self.headers_a)
        self.assertEqual(len(resp.data["data"]["employees"]), 0)
        # but is selectable at shop B's device
        issued_b = make_device(self.shop_b, device_uid="dev-b")
        resp = self.kiosk.get(
            EMPLOYEES_URL,
            **device_headers("dev-b", issued_b.plaintext_token),
        )
        self.assertEqual(len(resp.data["data"]["employees"]), 1)

    def test_deactivation_preserves_history(self):
        self.kiosk.post(
            CHECKIN_URL, {"employee_id": self.employee.id}, **self.headers_a
        )
        self.kiosk.post(
            "/api/v1/attendance/check-out/",
            {"employee_id": self.employee.id},
            **self.headers_a,
        )
        self.client.post(f"{EMP_URL}{self.employee.id}/deactivate/")
        resp = self.client.get(f"{BASE}/reports/events/?include_test=true")
        rows = resp.data["data"]["results"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["employee_ref"], self.employee.employee_code)

    def test_assignment_with_shift(self):
        resp = self.client.post(
            f"{BASE}/shifts/",
            {"shop": self.shop_a.id, "name": "Day", "start_time": "09:00", "end_time": "18:00"},
            format="json",
        )
        shift_id = resp.data["id"]
        resp = self.client.patch(
            f"{BASE}/assignments/{self.assignment.id}/",
            {"shift": shift_id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["shift"], shift_id)
