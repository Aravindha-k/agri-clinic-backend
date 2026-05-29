from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from tracking.models import LocationLog, WorkDay


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
        self.emp_client.force_authenticate(user=self.employee)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other)

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
        self._start_workday()
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
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 2)

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
