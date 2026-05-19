from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from tracking.models import WorkDay
from tracking.selectors import _live_key
from tracking.workday_utils import (
    MAX_WORKDAY_DURATION,
    expire_old_workdays,
    expire_overlong_workdays_for_user,
    is_workday_within_duration,
    workday_scheduled_end,
)


class WorkdayExpiryTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_wd", password="x", is_staff=True, is_superuser=True
        )
        self.employee = User.objects.create_user(username="emp_wd", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="WD-001",
            phone="9000000999",
            is_active_employee=True,
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.emp_client = APIClient()
        self.emp_client.force_authenticate(user=self.employee)

    def _active_workday(self, *, hours_ago=1):
        now = timezone.now()
        return WorkDay.objects.create(
            user=self.employee,
            date=now.date(),
            start_time=now - timedelta(hours=hours_ago),
            is_active=True,
            last_heartbeat=now - timedelta(minutes=2),
        )

    def test_active_workday_under_9_hours_remains_working(self):
        wd = self._active_workday(hours_ago=2)
        self.assertEqual(expire_old_workdays(), 0)
        wd.refresh_from_db()
        self.assertTrue(wd.is_active)
        self.assertTrue(is_workday_within_duration(wd))

    def test_active_workday_over_9_hours_becomes_auto_ended(self):
        wd = self._active_workday(hours_ago=10)
        cache.set(
            _live_key(self.employee.pk),
            {"user_id": self.employee.pk, "latitude": 1, "longitude": 2},
            timeout=60,
        )
        self.assertEqual(expire_old_workdays(), 1)
        wd.refresh_from_db()
        self.assertFalse(wd.is_active)
        self.assertTrue(wd.auto_ended)
        self.assertEqual(wd.end_time, workday_scheduled_end(wd.start_time))
        self.assertIsNone(cache.get(_live_key(self.employee.pk)))

    def test_admin_tracking_no_longer_shows_working_after_expiry(self):
        self._active_workday(hours_ago=12)
        r = self.admin_client.get("/api/v1/tracking/admin/status/")
        self.assertEqual(r.status_code, 200)
        rows = {row["user_id"]: row for row in r.data}
        self.assertEqual(rows[self.employee.id]["work_status"], "NOT_WORKING")

    def test_employee_can_start_new_day_after_auto_ended(self):
        self._active_workday(hours_ago=11)
        expire_overlong_workdays_for_user(self.employee)
        r = self.emp_client.post("/api/v1/tracking/workday/start/", {}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(
            WorkDay.objects.filter(user=self.employee, is_active=True).exists()
        )

    def test_current_workday_returns_expired_message(self):
        wd = self._active_workday(hours_ago=10)
        expire_overlong_workdays_for_user(self.employee)
        r = self.emp_client.get("/api/v1/tracking/workday/current/")
        self.assertEqual(r.status_code, 404)
        self.assertIn("auto-ended", r.data["detail"].lower())
        wd.refresh_from_db()
        self.assertFalse(wd.is_active)

    def test_employee_stats_endpoint_returns_200(self):
        r = self.admin_client.get("/api/v1/tracking/employee-stats/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("online", r.data)

    def test_admin_status_endpoint_returns_200(self):
        r = self.admin_client.get("/api/v1/tracking/admin/status/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)

    def test_employee_summary_endpoint_returns_200(self):
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/summary/"
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("employee_id", r.data)
        self.assertIn("movement_status", r.data)

    def test_expired_employee_not_online_or_working(self):
        self._active_workday(hours_ago=15)
        r = self.admin_client.get("/api/v1/tracking/admin/status/")
        self.assertEqual(r.status_code, 200)
        row = next(x for x in r.data if x["user_id"] == self.employee.id)
        self.assertEqual(row["work_status"], "NOT_WORKING")
        self.assertEqual(row["connection"], "OFFLINE")
        self.assertFalse(row.get("active_workday", True))
        self.assertIn(row.get("movement_status"), ("stopped", "idle"))

    def test_is_workday_within_duration_accepts_positional_now(self):
        wd = self._active_workday(hours_ago=1)
        now = timezone.now()
        self.assertTrue(is_workday_within_duration(wd, now))
        self.assertTrue(is_workday_within_duration(wd, now=now))
