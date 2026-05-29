from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.device_sessions import DEVICE_SESSION_HEADER
from accounts.models import EmployeeDeviceSession, EmployeeProfile


class DeviceSessionTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="ds_admin",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="ds_emp", password="secret123")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="DS-001",
            phone="9000000888",
            is_active_employee=True,
        )
        self.client = APIClient()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _mobile_login(self):
        return self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "DS-001",
                "password": "secret123",
                "device_name": "Pixel Test",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )

    def test_mobile_login_returns_device_session_id(self):
        r = self._mobile_login()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("device_session_id", r.data)
        self.assertTrue(
            EmployeeDeviceSession.objects.filter(
                user=self.employee, is_active=True
            ).exists()
        )

    def test_latest_login_invalidates_previous_session(self):
        r1 = self._mobile_login()
        old_session = r1.data["device_session_id"]
        r2 = self._mobile_login()
        new_session = r2.data["device_session_id"]
        self.assertNotEqual(old_session, new_session)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r1.data['access']}",
            HTTP_X_DEVICE_SESSION=old_session,
        )
        r_conflict = self.client.post(
            "/api/v1/tracking/workday/start/", {}, format="json"
        )
        self.assertEqual(r_conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(r_conflict.data.get("code"), "DEVICE_SESSION_CONFLICT")

    def test_workday_start_requires_device_session_header(self):
        r = self._mobile_login()
        token = r.data["access"]
        session_id = r.data["device_session_id"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r_no_header = self.client.post(
            "/api/v1/tracking/workday/start/", {}, format="json"
        )
        self.assertEqual(r_no_header.status_code, status.HTTP_409_CONFLICT)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_DEVICE_SESSION=session_id,
        )
        r_ok = self.client.post(
            "/api/v1/tracking/workday/start/", {}, format="json"
        )
        self.assertEqual(r_ok.status_code, status.HTTP_201_CREATED)

    def test_admin_route_not_requires_device_session(self):
        r = self.admin_client.get(
            "/api/v1/tracking/admin/employee/{}/route/?date=2026-05-29".format(
                self.employee.id
            )
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data.get("success"))

    def test_admin_employee_list_includes_device_status(self):
        self._mobile_login()
        r = self.admin_client.get("/api/v1/employees/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        rows = r.data.get("results") or r.data.get("data", {}).get("results") or []
        row = next(x for x in rows if x.get("employee_id") == "DS-001")
        self.assertIn("device_status", row)
        self.assertTrue(row["device_status"]["is_active"])
