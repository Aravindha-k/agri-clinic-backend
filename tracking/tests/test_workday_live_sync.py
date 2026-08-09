"""Start Work Day must sync immediately into admin Live Tracking."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from tracking.models import DutySession, EmployeeLiveLocation, LocationLog, WorkDay
from tracking.selectors import _live_key


class WorkdayLiveTrackingSyncTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="sync_admin",
            password="x",
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            username="sync_emp",
            password="secret123",
        )
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="SYNC-001",
            phone="9000000999",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self._auth_employee()

        # Stale GPS from a previous day — must not win after a fresh Start Work Day.
        old_at = timezone.now() - timedelta(days=1)
        stale_workday = WorkDay.objects.create(
            user=self.employee,
            date=timezone.localdate() - timedelta(days=1),
            start_time=old_at,
            end_time=old_at + timedelta(hours=1),
            is_active=False,
            latitude=Decimal("10.000000"),
            longitude=Decimal("70.000000"),
        )
        EmployeeLiveLocation.objects.create(
            user=self.employee,
            latitude=Decimal("10.000000"),
            longitude=Decimal("70.000000"),
            recorded_at=old_at,
        )
        LocationLog.objects.create(
            user=self.employee,
            workday=stale_workday,
            latitude=Decimal("10.000000"),
            longitude=Decimal("70.000000"),
            recorded_at=old_at,
        )
        cache.set(
            _live_key(self.employee.pk),
            {
                "user_id": self.employee.pk,
                "latitude": 10.0,
                "longitude": 70.0,
                "timestamp": old_at.isoformat(),
            },
            timeout=900,
        )

    def _auth_employee(self):
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "SYNC-001",
                "password": "secret123",
                "device_name": "Sync Phone",
                "device_model": "Pixel",
                "platform": "android",
                "app_version": "2.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.token = r.data["access"]
        self.session_id = r.data["device_session_id"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_DEVICE_SESSION=self.session_id,
        )

    def _start_work(self, lat=12.9716, lng=77.5946):
        return self.client.post(
            "/api/v1/mobile/work/start/",
            {"latitude": lat, "longitude": lng},
            format="json",
        )

    def _live_row(self):
        r = self.admin_client.get("/api/admin/tracking/live/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            r.get("Cache-Control"),
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        rows = [
            e
            for e in r.data["data"]["employees"]
            if e["user_id"] == self.employee.id
        ]
        self.assertEqual(len(rows), 1)
        return r, rows[0]

    def test_start_workday_creates_one_active_session(self):
        r = self._start_work()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            DutySession.objects.filter(user=self.employee, is_active=True).count(),
            1,
        )
        self.assertEqual(
            WorkDay.objects.filter(user=self.employee, is_active=True).count(),
            1,
        )
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        self.assertEqual(duty.user_id, self.employee.pk)
        self.assertEqual(duty.workday.user_id, self.employee.pk)

    def test_live_tracking_immediately_shows_working_with_start_gps(self):
        start = self._start_work(12.9716, 77.5946)
        self.assertEqual(start.status_code, status.HTTP_200_OK)
        duty_id = start.data["data"]["duty_session_id"]

        response, row = self._live_row()
        self.assertTrue(row["is_on_duty"])
        self.assertTrue(row["active_workday"])
        self.assertEqual(row["duty_status"], "ON_DUTY")
        self.assertEqual(row["employee_id"], "SYNC-001")
        self.assertEqual(row["duty_session_id"], duty_id)
        self.assertEqual(row["connection"], "ONLINE")
        self.assertEqual(row["gps_status"], "GPS_ACTIVE")
        self.assertAlmostEqual(row["latitude"], 12.9716, places=4)
        self.assertAlmostEqual(row["longitude"], 77.5946, places=4)
        self.assertIsNotNone(row["last_gps_update"])
        self.assertIsNotNone(row["started_at"])
        self.assertIsNotNone(row["expected_end_at"])
        self.assertTrue(row["device_status"]["is_active"])
        self.assertIsNotNone(row["last_login"])
        self.assertIsNotNone(row["last_seen"])
        self.assertEqual(row["device_information"]["platform"], "android")
        self.assertGreaterEqual(response.data["data"]["online_count"], 1)

        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertEqual(live.duty_session_id, duty_id)
        self.assertAlmostEqual(float(live.latitude), 12.9716, places=4)

    def test_admin_status_prefers_fresh_live_gps_over_stale_location_log(self):
        self._start_work(12.9800, 77.6000)
        r = self.admin_client.get("/api/v1/tracking/admin/status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            r.get("Cache-Control"),
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        row = next(item for item in r.data if item["user_id"] == self.employee.id)
        self.assertEqual(row["work_status"], "WORKING")
        self.assertTrue(row["active_workday"])
        self.assertEqual(row["connection"], "ONLINE")
        self.assertAlmostEqual(row["last_latitude"], 12.9800, places=4)
        self.assertAlmostEqual(row["last_longitude"], 77.6000, places=4)
        self.assertNotEqual(row["last_latitude"], 10.0)

    def test_repeat_start_workday_is_idempotent(self):
        first = self._start_work(12.9716, 77.5946)
        duty_id = first.data["data"]["duty_session_id"]
        started_at = first.data["data"]["started_at"]

        second = self._start_work(12.9720, 77.5950)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["data"]["duty_session_id"], duty_id)
        self.assertEqual(second.data["data"]["started_at"], started_at)
        self.assertEqual(
            DutySession.objects.filter(user=self.employee, is_active=True).count(),
            1,
        )
        self.assertEqual(
            WorkDay.objects.filter(user=self.employee, is_active=True).count(),
            1,
        )

        _, row = self._live_row()
        self.assertEqual(row["duty_session_id"], duty_id)
        self.assertAlmostEqual(row["latitude"], 12.9720, places=4)
        self.assertEqual(row["connection"], "ONLINE")

    def test_live_tracking_response_is_not_stale_cached_payload(self):
        self._start_work(13.0827, 80.2707)
        r1, row1 = self._live_row()
        self.assertAlmostEqual(row1["latitude"], 13.0827, places=4)

        # Simulate a stale Redis payload that must not override the DB live row.
        cache.set(
            _live_key(self.employee.pk),
            {
                "user_id": self.employee.pk,
                "latitude": 1.0,
                "longitude": 2.0,
                "timestamp": (timezone.now() - timedelta(hours=5)).isoformat(),
            },
            timeout=900,
        )
        r2, row2 = self._live_row()
        self.assertAlmostEqual(row2["latitude"], 13.0827, places=4)
        self.assertNotEqual(row2["latitude"], 1.0)
        self.assertEqual(
            r1.get("Cache-Control"),
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.assertEqual(
            r2.get("Cache-Control"),
            "no-store, no-cache, must-revalidate, max-age=0",
        )

    def test_null_island_coords_rejected_on_start_and_gps_update(self):
        start = self._start_work(0, 0)
        self.assertEqual(start.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(start.data.get("code"), "INVALID_COORDS")
        self.assertEqual(
            DutySession.objects.filter(user=self.employee, is_active=True).count(),
            0,
        )

        ok_start = self._start_work(12.9716, 77.5946)
        self.assertEqual(ok_start.status_code, status.HTTP_200_OK)

        gps = self.client.post(
            "/api/tracking/location/update/",
            {"latitude": 0, "longitude": 0},
            format="json",
        )
        self.assertEqual(gps.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(gps.data.get("code"), "INVALID_COORDS")

        near_zero = self.client.post(
            "/api/tracking/location/update/",
            {"latitude": 0.0, "longitude": 0.0001},
            format="json",
        )
        self.assertEqual(near_zero.status_code, status.HTTP_200_OK)
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertAlmostEqual(float(live.latitude), 0.0, places=5)
        self.assertAlmostEqual(float(live.longitude), 0.0001, places=5)

    @override_settings(
        LIVE_TRACKING_ONLINE_SECONDS=7 * 60,
        LIVE_TRACKING_STALE_SECONDS=15 * 60,
    )
    def test_live_and_status_online_agree_after_six_minutes(self):
        """Former 5m Status vs 7m Live mismatch window must stay ONLINE on both."""
        start = self._start_work(12.9716, 77.5946)
        self.assertEqual(start.status_code, status.HTTP_200_OK)

        aged = timezone.now() - timedelta(minutes=6)
        WorkDay.objects.filter(user=self.employee, is_active=True).update(
            last_heartbeat=aged
        )
        DutySession.objects.filter(user=self.employee, is_active=True).update(
            last_heartbeat=aged
        )
        EmployeeLiveLocation.objects.filter(user=self.employee).update(
            last_heartbeat_at=aged,
            recorded_at=aged,
        )

        _, live_row = self._live_row()
        self.assertEqual(live_row["connection"], "ONLINE")
        self.assertEqual(live_row["tracking_status"], "ONLINE")

        status_resp = self.admin_client.get("/api/v1/tracking/admin/status/")
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK)
        status_row = next(
            item for item in status_resp.data if item["user_id"] == self.employee.id
        )
        self.assertEqual(status_row["connection"], "ONLINE")
        self.assertTrue(status_row["is_online"])
