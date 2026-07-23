"""Heartbeat-backed live tracking contract tests."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from tracking.live_tracking_service import (
    TRACKING_NO_LOCATION,
    TRACKING_OFFLINE,
    TRACKING_ONLINE,
    TRACKING_STALE,
    apply_heartbeat,
    resolve_tracking_status,
    update_live_state_from_gps,
)
from tracking.models import DutySession, EmployeeLiveLocation, EmployeeRoutePoint, WorkDay
from tracking.duty_service import end_duty, start_duty


@override_settings(
    LIVE_TRACKING_ONLINE_SECONDS=7 * 60,
    LIVE_TRACKING_STALE_SECONDS=15 * 60,
)
class TrackingStatusRulesTest(TestCase):
    def test_fresh_heartbeat_online(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now - timedelta(minutes=5),
                latitude=12.97,
                longitude=77.59,
                gps_enabled=True,
                location_permission_status="granted",
                background_tracking_enabled=True,
                now=now,
            ),
            TRACKING_ONLINE,
        )

    def test_eight_minute_heartbeat_stale(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now - timedelta(minutes=8),
                latitude=12.97,
                longitude=77.59,
                gps_enabled=True,
                now=now,
            ),
            TRACKING_STALE,
        )

    def test_sixteen_minute_heartbeat_offline(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now - timedelta(minutes=16),
                latitude=12.97,
                longitude=77.59,
                gps_enabled=True,
                now=now,
            ),
            TRACKING_OFFLINE,
        )

    def test_gps_disabled_offline(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now,
                latitude=12.97,
                longitude=77.59,
                gps_enabled=False,
                now=now,
            ),
            TRACKING_OFFLINE,
        )

    def test_permission_denied_offline(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now,
                latitude=12.97,
                longitude=77.59,
                permission_granted=False,
                now=now,
            ),
            TRACKING_OFFLINE,
        )

    def test_tracking_service_off_offline(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now,
                latitude=12.97,
                longitude=77.59,
                tracking_service_active=False,
                now=now,
            ),
            TRACKING_OFFLINE,
        )

    def test_stationary_fresh_heartbeat_online(self):
        """No new GPS row required — heartbeat alone keeps Online."""
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now - timedelta(minutes=4),
                latitude=12.97,
                longitude=77.59,
                gps_enabled=True,
                now=now,
            ),
            TRACKING_ONLINE,
        )

    def test_active_duty_no_coords_no_location_yet(self):
        now = timezone.now()
        self.assertEqual(
            resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=now,
                latitude=None,
                longitude=None,
                gps_enabled=True,
                now=now,
            ),
            TRACKING_NO_LOCATION,
        )


class HeartbeatLiveTrackingAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="hb_admin", password="x", is_staff=True
        )
        self.employee = User.objects.create_user(username="hb_emp", password="secret123")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="HB-001",
            phone="9000000701",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        login = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "HB-001",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
            HTTP_X_DEVICE_SESSION=login.data["device_session_id"],
        )

    def _start(self, **coords):
        body = {"latitude": 12.9716, "longitude": 77.5946, **coords}
        return self.client.post("/api/v1/tracking/duty/start/", body, format="json")

    def test_heartbeat_without_movement_keeps_online_no_route_point(self):
        self._start()
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        before_routes = EmployeeRoutePoint.objects.filter(duty_session=duty).count()
        r = self.client.post(
            "/api/v1/tracking/heartbeat/",
            {
                "duty_session_id": duty.pk,
                "gps_enabled": True,
                "permission_granted": True,
                "tracking_service_active": True,
                "client_heartbeat_id": "hb-1",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        data = r.data.get("data") or r.data
        self.assertEqual(data["tracking_status"], TRACKING_ONLINE)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(duty_session=duty).count(),
            before_routes,
        )
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertIsNotNone(live.last_heartbeat_at)
        row = self.admin_client.get("/api/admin/tracking/live/").data["data"]
        emp = next(e for e in row["employees"] if e["user_id"] == self.employee.id)
        self.assertEqual(emp["tracking_status"], TRACKING_ONLINE)
        self.assertEqual(emp["connection"], TRACKING_ONLINE)

    def test_repeated_heartbeat_idempotent(self):
        self._start()
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        payload = {
            "duty_session_id": duty.pk,
            "client_heartbeat_id": "hb-dup",
            "gps_enabled": True,
        }
        r1 = self.client.post("/api/v1/tracking/heartbeat/", payload, format="json")
        r2 = self.client.post("/api/v1/tracking/heartbeat/", payload, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue((r2.data.get("data") or r2.data).get("duplicate"))

    def test_stale_heartbeat_cannot_overwrite_newer(self):
        self._start()
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        now = timezone.now()
        apply_heartbeat(
            self.employee,
            {
                "duty_session_id": duty.pk,
                "recorded_at": now.isoformat(),
                "client_heartbeat_id": "new",
            },
        )
        result = apply_heartbeat(
            self.employee,
            {
                "duty_session_id": duty.pk,
                "recorded_at": (now - timedelta(minutes=2)).isoformat(),
                "client_heartbeat_id": "old",
            },
        )
        self.assertTrue(result["stale_ignored"])
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertGreaterEqual(live.last_heartbeat_at, now - timedelta(seconds=2))

    def test_wrong_duty_rejected(self):
        self._start()
        r = self.client.post(
            "/api/v1/tracking/heartbeat/",
            {"duty_session_id": 999999, "gps_enabled": True},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_older_gps_does_not_replace_newer_coordinate(self):
        duty = start_duty(self.employee, latitude=12.97, longitude=77.59).duty
        now = timezone.now()
        update_live_state_from_gps(
            user=self.employee,
            duty=duty,
            latitude=12.98,
            longitude=77.60,
            recorded_at=now,
        )
        update_live_state_from_gps(
            user=self.employee,
            duty=duty,
            latitude=11.0,
            longitude=76.0,
            recorded_at=now - timedelta(minutes=5),
        )
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertAlmostEqual(float(live.latitude), 12.98, places=4)

    def test_heartbeat_does_not_create_route_history_points(self):
        self._start()
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        start_count = EmployeeRoutePoint.objects.filter(duty_session=duty).count()
        for i in range(3):
            self.client.post(
                "/api/v1/tracking/heartbeat/",
                {
                    "duty_session_id": duty.pk,
                    "client_heartbeat_id": f"hb-route-{i}",
                    "gps_enabled": True,
                },
                format="json",
            )
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(duty_session=duty).count(),
            start_count,
        )

    def test_admin_excludes_ended_duty(self):
        self._start()
        end_duty(self.employee, latitude=12.97, longitude=77.59)
        r = self.admin_client.get("/api/admin/tracking/live/")
        ids = [e["user_id"] for e in r.data["data"]["employees"]]
        self.assertNotIn(self.employee.id, ids)

    def test_no_location_employee_in_live_list(self):
        self.client.post("/api/v1/tracking/duty/start/", {}, format="json")
        self.client.post(
            "/api/v1/tracking/heartbeat/",
            {"gps_enabled": True, "permission_granted": True},
            format="json",
        )
        r = self.admin_client.get("/api/admin/tracking/live/")
        emp = next(
            e for e in r.data["data"]["employees"] if e["user_id"] == self.employee.id
        )
        self.assertEqual(emp["tracking_status"], TRACKING_NO_LOCATION)
        self.assertIsNone(emp["latitude"])
        self.assertIsNone(emp["longitude"])
        self.assertEqual(emp["duty_status"], "ON_DUTY")

    def test_gps_off_while_duty_working(self):
        self._start()
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        self.client.post(
            "/api/v1/tracking/heartbeat/",
            {
                "duty_session_id": duty.pk,
                "gps_enabled": False,
                "permission_granted": True,
                "tracking_service_active": True,
            },
            format="json",
        )
        emp = next(
            e
            for e in self.admin_client.get("/api/admin/tracking/live/").data["data"][
                "employees"
            ]
            if e["user_id"] == self.employee.id
        )
        self.assertEqual(emp["tracking_status"], TRACKING_OFFLINE)
        self.assertEqual(emp["duty_status"], "ON_DUTY")
        self.assertTrue(emp["is_on_duty"])
        self.assertIsNotNone(emp["latitude"])
