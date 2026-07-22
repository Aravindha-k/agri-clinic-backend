"""Route History Start marker must follow DutySession Work Day start coords."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from tracking.day_map_service import SOURCE_DUTY_START, SOURCE_WORKDAY_START, build_duty_day_map
from tracking.duty_service import start_duty
from tracking.gps_service import apply_gps_point
from tracking.models import DutySession, EmployeeRoutePoint


class RouteHistoryStartMarkerTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="rh_admin", password="x", is_staff=True, is_superuser=True
        )
        self.employee = User.objects.create_user(username="rh_emp", password="Secret123!")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="RH-001",
            phone="9000000101",
            is_active_employee=True,
            can_login=True,
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def test_start_work_day_persists_coords_and_admin_route_returns_start_stop(self):
        duty = start_duty(
            self.employee, latitude=12.9716, longitude=77.5946
        ).duty
        self.assertEqual(duty.latitude, Decimal("12.971600"))
        self.assertEqual(duty.longitude, Decimal("77.594600"))
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(
                duty_session=duty, point_type=EmployeeRoutePoint.POINT_START
            ).exists()
        )

        day_map = build_duty_day_map(duty, include_live_location=False)
        self.assertIsNotNone(day_map["start_marker"])
        self.assertEqual(day_map["start_marker"]["source"], SOURCE_WORKDAY_START)

        r = self.admin_client.get(
            f"/api/admin/tracking/employee/{self.employee.id}/today-route/"
        )
        self.assertEqual(r.status_code, 200, r.data)
        data = r.data["data"]
        self.assertEqual(data["duty_session_id"], duty.pk)
        self.assertTrue(data["has_start_marker"])
        self.assertIsNotNone(data["start_marker"])
        self.assertEqual(data["markers"]["start"]["source"], SOURCE_WORKDAY_START)
        self.assertEqual(data["start_latitude"], float(duty.latitude))
        self.assertEqual(data["start_longitude"], float(duty.longitude))
        stop_types = [s["type"] for s in data["stops"]]
        self.assertIn("start", stop_types)
        self.assertNotIn("visit", stop_types)

    def test_start_without_coords_then_first_gps_backfills_duty_start(self):
        duty = start_duty(self.employee).duty
        self.assertIsNone(duty.latitude)
        self.assertIsNone(duty.longitude)
        self.assertFalse(
            EmployeeRoutePoint.objects.filter(
                duty_session=duty, point_type=EmployeeRoutePoint.POINT_START
            ).exists()
        )
        empty_map = build_duty_day_map(duty, include_live_location=False)
        self.assertIsNone(empty_map["start_marker"])

        apply_gps_point(
            self.employee,
            duty,
            {
                "latitude": 11.1,
                "longitude": 79.2,
                "accuracy": 5,
                "recorded_at": timezone.now().isoformat(),
            },
        )
        duty.refresh_from_db()
        self.assertEqual(duty.latitude, Decimal("11.100000"))
        self.assertEqual(duty.longitude, Decimal("79.200000"))
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(
                duty_session=duty, point_type=EmployeeRoutePoint.POINT_START
            ).exists()
        )
        day_map = build_duty_day_map(duty, include_live_location=False)
        self.assertIsNotNone(day_map["start_marker"])
        self.assertIn(
            day_map["start_marker"]["source"],
            {SOURCE_WORKDAY_START, SOURCE_DUTY_START},
        )

    def test_route_history_uses_same_duty_session_as_business_date(self):
        duty = start_duty(
            self.employee, latitude=10.1, longitude=78.1
        ).duty
        # GPS heartbeats must not become the Start marker source.
        EmployeeRoutePoint.objects.create(
            user=self.employee,
            duty_session=duty,
            latitude=Decimal("12.000000"),
            longitude=Decimal("77.000000"),
            recorded_at=timezone.now(),
            point_type=EmployeeRoutePoint.POINT_GPS,
            client_point_id="gps-1",
        )
        day_map = build_duty_day_map(duty, include_live_location=False)
        self.assertAlmostEqual(day_map["start_marker"]["latitude"], 10.1, places=4)

        r = self.admin_client.get(
            f"/api/admin/tracking/employee/{self.employee.id}/route/",
            {"date": str(timezone.localdate())},
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["data"]["duty_session_id"], duty.pk)
        self.assertEqual(r.data["data"]["business_date"], str(duty.date))
        self.assertAlmostEqual(r.data["data"]["start_marker"]["latitude"], 10.1, places=4)

    @override_settings(DEBUG=True)
    def test_debug_logs_when_start_coords_null(self):
        duty = DutySession.objects.create(
            user=self.employee,
            date=timezone.localdate(),
            start_time=timezone.now(),
            is_active=True,
        )
        with self.assertLogs("tracking.day_map_service", level="WARNING") as cm:
            build_duty_day_map(duty, include_live_location=False)
        self.assertTrue(any("START_COORDS_NULL" in line for line in cm.output))
