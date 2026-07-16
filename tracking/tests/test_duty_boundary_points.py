"""Final phase: explicit WORKDAY_START / WORKDAY_END route points."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmployeeDeviceSession, EmployeeProfile
from tracking.day_map_service import build_duty_day_map, SOURCE_WORKDAY_END, SOURCE_WORKDAY_START
from tracking.duty_expiry import complete_duty_as_auto_expired
from tracking.duty_service import end_duty, start_duty
from tracking.models import EmployeeRoutePoint
from tracking.gps_service import duty_end_client_point_id, duty_start_client_point_id


def _employee(username="bound_emp", employee_id="BND-001"):
    user = User.objects.create_user(username=username, password="secret123")
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000333",
        is_active_employee=True,
    )
    return user


class DutyBoundaryRoutePointTests(TestCase):
    def setUp(self):
        self.user = _employee()

    def test_start_creates_one_workday_start_point(self):
        duty = start_duty(self.user, latitude=12.9716, longitude=77.5946).duty
        points = EmployeeRoutePoint.objects.filter(
            duty_session=duty, point_type=EmployeeRoutePoint.POINT_START
        )
        self.assertEqual(points.count(), 1)
        pt = points.get()
        self.assertEqual(pt.client_point_id, duty_start_client_point_id(duty.pk))
        self.assertEqual(pt.user_id, self.user.pk)
        self.assertTrue(pt.is_permanent)

    def test_repeated_start_no_duplicate(self):
        start_duty(self.user, latitude=12.9716, longitude=77.5946)
        start_duty(self.user, latitude=12.98, longitude=77.60)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                user=self.user, point_type=EmployeeRoutePoint.POINT_START
            ).count(),
            1,
        )

    def test_start_without_coords_does_not_fail(self):
        duty = start_duty(self.user).duty
        self.assertTrue(duty.is_active)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(duty_session=duty).count(),
            0,
        )

    def test_manual_end_creates_one_workday_end_point(self):
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        ended = end_duty(self.user, latitude=12.98, longitude=77.60)
        self.assertEqual(ended.pk, duty.pk)
        points = EmployeeRoutePoint.objects.filter(
            duty_session=duty, point_type=EmployeeRoutePoint.POINT_END
        )
        self.assertEqual(points.count(), 1)
        self.assertEqual(
            points.get().client_point_id, duty_end_client_point_id(duty.pk)
        )

    def test_repeated_end_no_duplicate(self):
        start_duty(self.user, latitude=12.97, longitude=77.59)
        end_duty(self.user, latitude=12.98, longitude=77.60)
        end_duty(self.user, latitude=13.0, longitude=77.61)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                user=self.user, point_type=EmployeeRoutePoint.POINT_END
            ).count(),
            1,
        )

    def test_auto_expiry_does_not_invent_end_point(self):
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        duty.start_time = timezone.now() - timedelta(hours=10)
        duty.save(update_fields=["start_time"])
        complete_duty_as_auto_expired(duty, trigger="test")
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                duty_session=duty, point_type=EmployeeRoutePoint.POINT_END
            ).count(),
            0,
        )

    def test_day_map_prefers_explicit_start_end(self):
        duty = start_duty(self.user, latitude=12.9716, longitude=77.5946).duty
        EmployeeRoutePoint.objects.create(
            user=self.user,
            duty_session=duty,
            latitude=12.0,
            longitude=77.0,
            recorded_at=duty.start_time + timedelta(minutes=5),
            point_type=EmployeeRoutePoint.POINT_GPS,
            client_point_id="mid-1",
            is_permanent=True,
        )
        end_duty(self.user, latitude=13.0, longitude=78.0)
        duty.refresh_from_db()
        day_map = build_duty_day_map(duty, viewer=self.user)
        self.assertIsNotNone(day_map["start_marker"])
        self.assertEqual(day_map["start_marker"]["source"], SOURCE_WORKDAY_START)
        self.assertAlmostEqual(day_map["start_marker"]["latitude"], 12.9716, places=4)
        self.assertIsNotNone(day_map["end_marker"])
        self.assertEqual(day_map["end_marker"]["source"], SOURCE_WORKDAY_END)
        self.assertAlmostEqual(day_map["end_marker"]["latitude"], 13.0, places=4)

    def test_wrong_employee_cannot_attach_boundary_point(self):
        _employee("other_b", "BND-002")
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        self.assertEqual(
            EmployeeRoutePoint.objects.get(
                duty_session=duty, point_type=EmployeeRoutePoint.POINT_START
            ).user_id,
            self.user.pk,
        )
        client = APIClient()
        login = client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "BND-002",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
            HTTP_X_DEVICE_SESSION=login.data["device_session_id"],
        )
        resp = client.get(f"/api/v1/tracking/duty/{duty.pk}/map/")
        self.assertEqual(resp.status_code, 404)


class DutyBoundaryConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required for concurrency")
        self.user = _employee("race_bnd", "RACE-BND")

    def _run_concurrently(self, operation):
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                return operation(user)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            return [future.result(timeout=15) for future in futures]

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_start_one_start_point(self):
        results = self._run_concurrently(
            lambda user: start_duty(user, latitude=12.9716, longitude=77.5946)
        )
        duty_ids = {r.duty.pk for r in results}
        self.assertEqual(len(duty_ids), 1)
        duty_id = next(iter(duty_ids))
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                duty_session_id=duty_id, point_type=EmployeeRoutePoint.POINT_START
            ).count(),
            1,
        )


class DutyBoundaryDeviceSessionTests(TestCase):
    def setUp(self):
        self.user = _employee("sess_bnd", "SESS-BND")
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "SESS-BND",
                "password": "secret123",
                "device_name": "PhoneA",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.token = r.data["access"]
        self.session_id = r.data["device_session_id"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_DEVICE_SESSION=self.session_id,
        )

    def test_revoked_device_cannot_write_start_location(self):
        EmployeeDeviceSession.objects.filter(session_key=self.session_id).update(
            is_active=False
        )
        resp = self.client.post(
            "/api/v1/tracking/duty/start/",
            {"latitude": 12.97, "longitude": 77.59},
            format="json",
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data.get("code"), "SESSION_REPLACED")
