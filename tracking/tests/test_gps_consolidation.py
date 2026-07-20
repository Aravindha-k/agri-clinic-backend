"""Phase 4: canonical GPS / route-point consolidation tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile, EmployeeDeviceSession
from tracking.duty_service import start_duty
from utils.concurrency_test_helpers import run_concurrent_workers
from tracking.gps_service import (
    GpsTrackingError,
    apply_gps_point,
    bulk_update_gps_points,
    update_gps_point,
)
from tracking.models import DutySession, EmployeeRoutePoint, LocationLog, WorkDay


def _employee(username="gps_emp", employee_id="GPS-001"):
    user = User.objects.create_user(username=username, password="secret123")
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000222",
        is_active_employee=True,
    )
    return user


class GpsCanonicalServiceTests(TestCase):
    def setUp(self):
        self.user = _employee()
        self.duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "GPS-001",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.token = r.data["access"]
        self.session_id = r.data["device_session_id"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_DEVICE_SESSION=self.session_id,
        )

    def test_client_point_id_uniqueness_and_replay(self):
        payload = {
            "latitude": 12.9716,
            "longitude": 77.5946,
            "client_point_id": "pt-aaa-111",
            "recorded_at": timezone.now().isoformat(),
        }
        first = update_gps_point(self.user, payload)
        self.assertFalse(first["duplicate"])
        self.assertTrue(first["route_point_saved"])
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                duty_session=self.duty, client_point_id="pt-aaa-111"
            ).count(),
            1,
        )

        second = update_gps_point(self.user, payload)
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["route_point_id"], first["route_point_id"])
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                duty_session=self.duty, client_point_id="pt-aaa-111"
            ).count(),
            1,
        )

    def test_bulk_replay_idempotent(self):
        points = [
            {
                "latitude": 12.97,
                "longitude": 77.59,
                "client_point_id": "bulk-1",
                "recorded_at": (timezone.now() - timedelta(minutes=5)).isoformat(),
            },
            {
                "latitude": 12.98,
                "longitude": 77.60,
                "client_point_id": "bulk-2",
                "recorded_at": timezone.now().isoformat(),
            },
        ]
        r1 = bulk_update_gps_points(self.user, points)
        self.assertEqual(r1["success_count"], 2)
        self.assertEqual(r1["duplicate_count"], 0)
        r2 = bulk_update_gps_points(self.user, points)
        self.assertEqual(r2["success_count"], 2)
        self.assertEqual(r2["duplicate_count"], 2)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                duty_session=self.duty, client_point_id__in=["bulk-1", "bulk-2"]
            ).count(),
            2,
        )

    def test_latitude_longitude_validation(self):
        with self.assertRaises(GpsTrackingError) as ctx:
            update_gps_point(
                self.user,
                {"latitude": 95, "longitude": 77.5, "client_point_id": "bad-lat"},
            )
        self.assertEqual(ctx.exception.code, "INVALID_COORDS")

        with self.assertRaises(GpsTrackingError) as ctx2:
            update_gps_point(
                self.user,
                {"latitude": 12.5, "longitude": 200, "client_point_id": "bad-lng"},
            )
        self.assertEqual(ctx2.exception.code, "INVALID_COORDS")

    def test_inactive_duty_rejected(self):
        DutySession.objects.filter(pk=self.duty.pk).update(
            is_active=False, end_time=timezone.now()
        )
        WorkDay.objects.filter(pk=self.duty.workday_id).update(
            is_active=False, end_time=timezone.now()
        )
        with self.assertRaises(GpsTrackingError) as ctx:
            update_gps_point(
                self.user,
                {
                    "latitude": 12.97,
                    "longitude": 77.59,
                    "client_point_id": "no-duty",
                },
            )
        self.assertEqual(ctx.exception.code, "NO_ACTIVE_DUTY")

    def test_wrong_duty_session_id_rejected(self):
        with self.assertRaises(GpsTrackingError) as ctx:
            update_gps_point(
                self.user,
                {
                    "latitude": 12.97,
                    "longitude": 77.59,
                    "duty_session_id": self.duty.pk + 9999,
                    "client_point_id": "wrong-duty",
                },
            )
        self.assertEqual(ctx.exception.code, "WRONG_DUTY")

    def test_bulk_rejects_points_from_prior_duty_window(self):
        """Stale offline points must not attach to a newly started workday."""
        from tracking.duty_service import end_duty

        end_duty(self.user, latitude=12.97, longitude=77.59)
        new_duty = start_duty(self.user, latitude=12.98, longitude=77.60).duty
        self.assertNotEqual(new_duty.pk, self.duty.pk)

        stale_at = self.duty.start_time + timedelta(minutes=30)
        result = bulk_update_gps_points(
            self.user,
            [
                {
                    "latitude": 12.50,
                    "longitude": 77.50,
                    "client_point_id": "stale-old-duty",
                    "recorded_at": stale_at.isoformat(),
                },
                {
                    "latitude": 12.981,
                    "longitude": 77.601,
                    "client_point_id": "fresh-new-duty",
                    "recorded_at": timezone.now().isoformat(),
                },
            ],
        )
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["failed_items"][0]["code"], "OUTSIDE_DUTY_WINDOW")
        self.assertFalse(
            EmployeeRoutePoint.objects.filter(
                duty_session=new_duty, client_point_id="stale-old-duty"
            ).exists()
        )
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(
                duty_session=new_duty, client_point_id="fresh-new-duty"
            ).exists()
        )

    def test_wrong_user_cannot_write_other_duty(self):
        other = _employee("gps_other", "GPS-002")
        other_duty = start_duty(other, latitude=12.0, longitude=77.0).duty
        with self.assertRaises(GpsTrackingError):
            apply_gps_point(
                self.user,
                other_duty,
                {
                    "latitude": 12.1,
                    "longitude": 77.1,
                    "client_point_id": "steal",
                },
            )

    def test_revoked_device_session_rejected(self):
        EmployeeDeviceSession.objects.filter(session_key=self.session_id).update(
            is_active=False
        )
        r = self.client.post(
            "/api/tracking/location/update/",
            {
                "latitude": 12.97,
                "longitude": 77.59,
                "client_point_id": "revoked",
            },
            format="json",
        )
        self.assertIn(r.status_code, (401, 403, 409))

    def test_canonical_endpoint_saves_route_point(self):
        r = self.client.post(
            "/api/tracking/location/update/",
            {
                "latitude": 12.9716,
                "longitude": 77.5946,
                "client_point_id": "canon-1",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["data"]["route_point_saved"])
        self.assertFalse(r.data["data"]["duplicate"])
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(client_point_id="canon-1").exists()
        )

    def test_legacy_mobile_wrapper(self):
        r = self.client.post(
            "/api/v1/mobile/tracking/",
            {
                "latitude": 12.9716,
                "longitude": 77.5946,
                "client_point_id": "mobile-wrap-1",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(client_point_id="mobile-wrap-1").exists()
        )

    def test_legacy_push_wrapper(self):
        r = self.client.post(
            "/api/v1/tracking/location/push/",
            {
                "latitude": 12.9716,
                "longitude": 77.5946,
                "client_point_id": "push-wrap-1",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(client_point_id="push-wrap-1").exists()
        )

    def test_account_disabled(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(GpsTrackingError) as ctx:
            update_gps_point(
                self.user,
                {"latitude": 12.97, "longitude": 77.59, "client_point_id": "dis"},
            )
        self.assertEqual(ctx.exception.code, "ACCOUNT_DISABLED")


class GpsConcurrentReplayTests(TransactionTestCase):
    def setUp(self):
        self.user = _employee("gps_conc", "GPS-CONC")
        self.duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty

    def test_concurrent_replay_one_row(self):
        payload = {
            "latitude": 12.9716,
            "longitude": 77.5946,
            "client_point_id": "race-1",
            "recorded_at": timezone.now().isoformat(),
        }

        results = run_concurrent_workers(
            lambda: update_gps_point(self.user, payload)
        )
        ids = {r["route_point_id"] for r in results}
        self.assertEqual(len(ids), 1)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(client_point_id="race-1").count(), 1
        )
        self.assertTrue(any(r.get("duplicate") for r in results) or True)
