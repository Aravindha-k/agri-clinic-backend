from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from tracking.models import DutySession, EmployeeRoutePoint, LocationLog, WorkDay


class RouteTrackingAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="route_admin",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="route_emp", password="x")
        self.other = User.objects.create_user(username="route_other", password="x")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="RT-001",
            phone="9000000111",
            is_active_employee=True,
        )
        EmployeeProfile.objects.create(
            user=self.other,
            employee_id="RT-002",
            phone="9000000222",
            is_active_employee=True,
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.emp_client = APIClient()
        self.other_client = APIClient()
        self._mobile_login(self.emp_client, "RT-001")
        self._mobile_login(self.other_client, "RT-002")

    def _mobile_login(self, client, employee_id, password="x"):
        r = client.post(
            "/api/v1/mobile/auth/login/",
            {"employee_id": employee_id, "password": password},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )
        return r

    def _start_workday(self, client=None):
        client = client or self.emp_client
        return client.post("/api/v1/tracking/workday/start/", {}, format="json")

    def test_start_workday_creates_workday_and_heartbeat(self):
        r = self._start_workday()
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        wd = WorkDay.objects.get(user=self.employee, is_active=True)
        self.assertIsNotNone(wd.start_time)
        self.assertIsNotNone(wd.last_heartbeat)

    def test_location_push_creates_location_log(self):
        self._start_workday()
        now = timezone.now()
        r = self.emp_client.post(
            "/api/v1/tracking/location/push/",
            {
                "latitude": "12.971600",
                "longitude": "77.594600",
                "accuracy": 8.5,
                "speed": 12.3,
                "heading": 90.0,
                "captured_at": now.isoformat(),
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 1)
        log = LocationLog.objects.get(user=self.employee)
        self.assertEqual(float(log.latitude), 12.9716)
        self.assertEqual(log.speed, 12.3)
        self.assertEqual(log.heading, 90.0)
        wd = WorkDay.objects.get(user=self.employee, is_active=True)
        self.assertIsNotNone(wd.last_heartbeat)

    def test_bulk_location_push_creates_multiple_rows(self):
        self.emp_client.post(
            "/api/v1/tracking/duty/start/",
            {"latitude": 12.9716, "longitude": 77.5946},
            format="json",
        )
        t0 = timezone.now()
        t1 = t0 + timedelta(minutes=1)
        r = self.emp_client.post(
            "/api/v1/tracking/location/bulk/",
            {
                "locations": [
                    {
                        "latitude": "12.971600",
                        "longitude": "77.594600",
                        "captured_at": t0.isoformat(),
                    },
                    {
                        "latitude": "12.972000",
                        "longitude": "77.595000",
                        "captured_at": t1.isoformat(),
                    },
                ]
            },
            format="json",
        )
        self.assertIn(r.status_code, (status.HTTP_201_CREATED, status.HTTP_207_MULTI_STATUS))
        self.assertEqual(r.data["data"]["success_count"], 2)
        self.assertGreaterEqual(r.data["data"]["route_points_saved"], 1)
        self.assertGreaterEqual(
            EmployeeRoutePoint.objects.filter(user=self.employee).count(),
            1,
        )
        self.assertGreaterEqual(LocationLog.objects.filter(user=self.employee).count(), 1)

    def test_admin_route_returns_chronological_points(self):
        self._start_workday()
        wd = WorkDay.objects.get(user=self.employee, is_active=True)
        today = timezone.localdate()
        t0 = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        t1 = t0 + timedelta(minutes=5)
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.97,
            longitude=77.59,
            recorded_at=t1,
        )
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.96,
            longitude=77.58,
            recorded_at=t0,
        )
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {"date": str(today)},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["success"])
        route = r.data["data"]["route"]
        self.assertEqual(r.data["data"]["total_points"], 2)
        self.assertEqual(route[0]["latitude"], 12.96)
        self.assertEqual(route[1]["latitude"], 12.97)
        self.assertEqual(r.data["data"]["points"], route)
        self.assertEqual(r.data["data"]["locations"], route)
        self.assertIn("captured_at", route[0])
        self.assertIn("created_at", route[0])
        self.assertIn("polyline", r.data["data"])
        self.assertEqual(len(r.data["data"]["polyline"]), 2)

    def test_admin_route_empty_when_no_logs(self):
        today = timezone.localdate()
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {"date": str(today)},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["success"])
        self.assertEqual(r.data["data"]["total_points"], 0)
        self.assertEqual(r.data["data"]["route"], [])

    def test_employee_cannot_access_admin_route(self):
        r = self.emp_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/"
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_location_push_uses_authenticated_user_only(self):
        self._start_workday()
        self.other_client.post("/api/v1/tracking/workday/start/", {}, format="json")
        r = self.other_client.post(
            "/api/v1/tracking/location/push/",
            {
                "latitude": "13.000000",
                "longitude": "77.600000",
                "user_id": self.employee.id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 0)
        self.assertEqual(LocationLog.objects.filter(user=self.other).count(), 1)

    def test_three_location_points_create_three_logs(self):
        self._start_workday()
        t0 = timezone.now()
        for index, (lat, lng) in enumerate(
            (
                ("12.971600", "77.594600"),
                ("12.972000", "77.595000"),
                ("12.972500", "77.595500"),
            )
        ):
            r = self.emp_client.post(
                "/api/v1/tracking/location/push/",
                {
                    "latitude": lat,
                    "longitude": lng,
                    "captured_at": (t0 + timedelta(minutes=index)).isoformat(),
                },
                format="json",
            )
            self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 3)

    def test_route_history_distance_positive_for_movement(self):
        self._start_workday()
        wd = WorkDay.objects.get(user=self.employee, is_active=True)
        today = timezone.localdate()
        t0 = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        coords = [
            (12.9716, 77.5946),
            (12.9720, 77.5950),
            (12.9725, 77.5955),
        ]
        for index, (lat, lng) in enumerate(coords):
            LocationLog.objects.create(
                user=self.employee,
                workday=wd,
                latitude=lat,
                longitude=lng,
                recorded_at=t0 + timedelta(minutes=index * 5),
            )
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {"date": str(today)},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["total_points"], 3)
        self.assertGreater(data["distance_km"], 0)
        self.assertNotEqual(data["start_time"], data["end_time"])

    def test_location_push_without_workday_returns_error(self):
        r = self.emp_client.post(
            "/api/v1/tracking/location/push/",
            {"latitude": "12.971600", "longitude": "77.594600"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_alias_endpoint_saves_multiple_rows(self):
        self._start_workday()
        t0 = timezone.now()
        r = self.emp_client.post(
            "/api/v1/tracking/locations/bulk/",
            {
                "locations": [
                    {
                        "latitude": "12.971600",
                        "longitude": "77.594600",
                        "timestamp": t0.isoformat(),
                    },
                    {
                        "latitude": "12.972000",
                        "longitude": "77.595000",
                        "timestamp": (t0 + timedelta(minutes=2)).isoformat(),
                    },
                ]
            },
            format="json",
        )
        self.assertIn(r.status_code, (status.HTTP_201_CREATED, status.HTTP_207_MULTI_STATUS))
        self.assertEqual(r.data["data"]["saved_count"], 2)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 2)

    def test_movement_based_three_points_route_distance(self):
        """Simulate movement-based points ~100m and ~500m apart."""
        self._start_workday()
        t0 = timezone.now()
        points = [
            ("12.971600", "77.594600", 0),
            ("12.972500", "77.594600", 5),  # ~100m north
            ("12.976100", "77.594600", 15),  # ~500m north of start
        ]
        for lat, lng, minutes in points:
            r = self.emp_client.post(
                "/api/v1/tracking/location/push/",
                {
                    "latitude": lat,
                    "longitude": lng,
                    "accuracy": 12,
                    "speed": 5.5,
                    "heading": 0,
                    "timestamp": (t0 + timedelta(minutes=minutes)).isoformat(),
                },
                format="json",
            )
            self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 3)
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {"date": str(timezone.localdate())},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["total_points"], 3)
        self.assertGreater(data["distance_km"], 0.4)
        self.assertNotEqual(data["start_time"], data["end_time"])

    def test_bulk_points_payload_key(self):
        self._start_workday()
        t0 = timezone.now()
        r = self.emp_client.post(
            "/api/v1/tracking/locations/bulk/",
            {
                "points": [
                    {
                        "latitude": 12.9716,
                        "longitude": 77.5946,
                        "accuracy": 15,
                        "speed": 3.2,
                        "heading": 120,
                        "timestamp": t0.isoformat(),
                    },
                    {
                        "latitude": 12.9720,
                        "longitude": 77.5950,
                        "accuracy": 14,
                        "speed": 4.0,
                        "heading": 125,
                        "timestamp": (t0 + timedelta(minutes=3)).isoformat(),
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data["data"]["saved_count"], 2)
        self.assertEqual(r.data["data"]["failed_count"], 0)
        self.assertEqual(r.data["data"]["errors"], [])

    def test_invalid_coordinates_rejected(self):
        self._start_workday()
        r = self.emp_client.post(
            "/api/v1/tracking/location/push/",
            {"latitude": 999, "longitude": 77.5946},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 0)

    def test_poor_accuracy_rejected_after_first_point(self):
        self._start_workday()
        r1 = self.emp_client.post(
            "/api/v1/tracking/location/push/",
            {
                "latitude": "12.971600",
                "longitude": "77.594600",
                "accuracy": 250,
            },
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        r2 = self.emp_client.post(
            "/api/v1/tracking/location/push/",
            {
                "latitude": "12.972000",
                "longitude": "77.595000",
                "accuracy": 250,
            },
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 1)

    def test_duplicate_point_rejected(self):
        self._start_workday()
        t0 = timezone.now()
        payload = {
            "latitude": "12.971600",
            "longitude": "77.594600",
            "timestamp": t0.isoformat(),
        }
        r1 = self.emp_client.post(
            "/api/v1/tracking/location/push/", payload, format="json"
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        r2 = self.emp_client.post(
            "/api/v1/tracking/location/push/", payload, format="json"
        )
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 1)

    def test_workday_locations_chronological(self):
        self._start_workday()
        wd = WorkDay.objects.get(user=self.employee, is_active=True)
        t0 = timezone.now()
        t1 = t0 + timedelta(minutes=3)
        LocationLog.objects.create(
            user=self.employee, workday=wd, latitude=12.1, longitude=77.1, recorded_at=t1
        )
        LocationLog.objects.create(
            user=self.employee, workday=wd, latitude=12.0, longitude=77.0, recorded_at=t0
        )
        r = self.emp_client.get(f"/api/v1/tracking/workday/{wd.id}/locations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data["results"]
        self.assertEqual(float(results[0]["latitude"]), 12.0)
        self.assertEqual(float(results[1]["latitude"]), 12.1)
