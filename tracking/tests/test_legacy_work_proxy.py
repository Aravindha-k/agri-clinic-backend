"""Phase 2: legacy work APIs proxy to DutySession."""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from tracking.duty_service import start_duty
from tracking.models import DutySession, WorkDay
from tracking.worklog import WorkLog


STRONG_PASSWORD = "SecurePass1!"


class LegacyWorkProxyTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(
            username="p2_emp", password=STRONG_PASSWORD
        )
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="P2-001",
            phone="9000000333",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()

    def _login(self):
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "P2-001",
                "password": STRONG_PASSWORD,
                "device_id": "p2-phone",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )
        return r

    def test_mobile_work_start_creates_duty_not_independent_workday_only(self):
        self._login()
        r = self.client.post(
            "/api/v1/mobile/work/start/",
            {"latitude": 12.1, "longitude": 79.1},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(DutySession.objects.filter(user=self.employee, is_active=True).count(), 1)
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        self.assertIsNotNone(duty.workday_id)
        self.assertTrue(WorkDay.objects.filter(id=duty.workday_id, is_active=True).exists())

    def test_repeated_legacy_start_reuses_same_duty_start_time(self):
        self._login()
        r1 = self.client.post("/api/v1/work/start/", {}, format="json")
        self.assertIn(r1.status_code, (200, 201))
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        started = duty.start_time
        r2 = self.client.post("/api/v1/work/start/", {}, format="json")
        self.assertIn(r2.status_code, (200, 201))
        duty.refresh_from_db()
        self.assertEqual(duty.start_time, started)
        self.assertEqual(
            DutySession.objects.filter(user=self.employee, is_active=True).count(), 1
        )

    def test_legacy_end_ends_duty(self):
        self._login()
        start_duty(self.employee)
        r = self.client.post("/api/v1/tracking/workday/end/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            DutySession.objects.filter(user=self.employee, is_active=True).exists()
        )

    def test_worklog_start_does_not_create_worklog_row(self):
        self._login()
        before = WorkLog.objects.count()
        r = self.client.post("/api/v1/tracking/work/start/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(WorkLog.objects.count(), before)
        self.assertTrue(
            DutySession.objects.filter(user=self.employee, is_active=True).exists()
        )

    def test_mobile_status_from_duty(self):
        self._login()
        start_duty(self.employee)
        r = self.client.get("/api/v1/mobile/work/status/")
        self.assertEqual(r.status_code, 200)
        data = r.data.get("data") or r.data
        self.assertEqual(data.get("work_status"), "started")
        self.assertIn("duty_session_id", data)

    def test_profile_work_status_from_duty(self):
        self._login()
        start_duty(self.employee)
        r = self.client.get("/api/v1/employees/me/")
        self.assertEqual(r.status_code, 200)
        data = r.data.get("data") or r.data
        self.assertTrue(data.get("work_status") is True or data.get("workday_status", {}).get("is_active"))
