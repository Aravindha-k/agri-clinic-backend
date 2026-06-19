from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from tracking.models import (
    DutySession,
    EmployeeLiveLocation,
    EmployeeRoutePoint,
    WorkDay,
)
from tracking.route_point_filter import MIN_ROUTE_INTERVAL_SECONDS
from visits.models import Visit


class DutyTrackingAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="dt_admin",
            password="x",
            is_staff=True,
        )
        self.employee = User.objects.create_user(username="dt_emp", password="secret123")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="DT-001",
            phone="9000000444",
            is_active_employee=True,
        )
        self.district = District.objects.create(name="DT District")
        self.village = Village.objects.create(name="DT Village", district=self.district)
        self.farmer = Farmer.objects.create(
            name="DT Farmer",
            phone="9333333333",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Maize", name_ta="Maize", is_active=True)
        self.today = timezone.localdate()

        self.client = APIClient()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self._auth_employee()

    def _auth_employee(self):
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "DT-001",
                "password": "secret123",
                "device_name": "Test Phone",
                "platform": "android",
                "app_version": "1.0.0",
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

    def _start_duty(self, lat=12.9716, lng=77.5946):
        return self.client.post(
            "/api/tracking/duty/start/",
            {"latitude": lat, "longitude": lng},
            format="json",
        )

    def _update_location(self, lat, lng, **extra):
        payload = {"latitude": lat, "longitude": lng, **extra}
        return self.client.post(
            "/api/tracking/location/update/",
            payload,
            format="json",
        )

    def test_duty_start_end(self):
        r = self._start_duty()
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        duty_id = r.data["data"]["duty_session_id"]
        self.assertTrue(DutySession.objects.filter(pk=duty_id, is_active=True).exists())
        self.assertTrue(WorkDay.objects.filter(user=self.employee, is_active=True).exists())

        r2 = self._start_duty()
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r2.data.get("code"), "DUTY_ALREADY_STARTED")

        r3 = self.client.post("/api/tracking/duty/end/", {}, format="json")
        self.assertEqual(r3.status_code, status.HTTP_200_OK)
        duty = DutySession.objects.get(pk=duty_id)
        self.assertFalse(duty.is_active)
        self.assertIsNotNone(duty.end_time)

    def test_live_location_update_or_create(self):
        self._start_duty()
        self._update_location(12.9716, 77.5946)
        self._update_location(12.9720, 77.5950)
        self.assertEqual(EmployeeLiveLocation.objects.filter(user=self.employee).count(), 1)
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertAlmostEqual(float(live.latitude), 12.9720, places=4)

    def test_route_throttle_skips_frequent_nearby_points(self):
        self._start_duty()
        t0 = timezone.now()
        r1 = self._update_location(12.9716, 77.5946, recorded_at=t0.isoformat())
        self.assertTrue(r1.data["data"]["route_point_saved"])
        r2 = self._update_location(
            12.97161,
            77.59461,
            recorded_at=(t0 + timedelta(seconds=5)).isoformat(),
        )
        self.assertFalse(r2.data["data"]["route_point_saved"])
        gps_points = EmployeeRoutePoint.objects.filter(
            user=self.employee,
            point_type=EmployeeRoutePoint.POINT_GPS,
        )
        self.assertEqual(gps_points.count(), 1)

    def test_route_saves_after_distance(self):
        self._start_duty()
        t0 = timezone.now()
        self._update_location(12.9716, 77.5946, recorded_at=t0.isoformat())
        r = self._update_location(
            12.9750,
            77.5980,
            recorded_at=(t0 + timedelta(seconds=10)).isoformat(),
        )
        self.assertTrue(r.data["data"]["route_point_saved"])
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                user=self.employee,
                point_type=EmployeeRoutePoint.POINT_GPS,
            ).count(),
            2,
        )

    def test_route_saves_after_interval(self):
        self._start_duty()
        t0 = timezone.now()
        self._update_location(12.9716, 77.5946, recorded_at=t0.isoformat())
        r = self._update_location(
            12.97161,
            77.59461,
            recorded_at=(t0 + timedelta(seconds=MIN_ROUTE_INTERVAL_SECONDS + 1)).isoformat(),
        )
        self.assertTrue(r.data["data"]["route_point_saved"])

    def test_visit_creates_permanent_route_point(self):
        self._start_duty()
        visit = Visit.objects.create(
            employee=self.employee,
            visit_date=self.today,
            visit_time=timezone.now().time(),
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=self.village,
            crop=self.crop,
            latitude=12.9800,
            longitude=77.6000,
        )
        point = EmployeeRoutePoint.objects.get(
            visit_id=visit.id,
            point_type=EmployeeRoutePoint.POINT_VISIT,
        )
        self.assertTrue(point.is_permanent)
        self.assertEqual(point.farmer_id, self.farmer.id)

    def test_admin_live_map(self):
        self._start_duty()
        self._update_location(12.9716, 77.5946)
        r = self.admin_client.get("/api/admin/tracking/live/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        employees = r.data["data"]["employees"]
        match = [e for e in employees if e["user_id"] == self.employee.id]
        self.assertEqual(len(match), 1)
        self.assertTrue(match[0]["is_on_duty"])
        self.assertIsNotNone(match[0]["latitude"])

    def test_admin_today_route(self):
        self._start_duty()
        t0 = timezone.now()
        self._update_location(12.9716, 77.5946, recorded_at=t0.isoformat())
        self._update_location(
            12.9750,
            77.5980,
            recorded_at=(t0 + timedelta(seconds=MIN_ROUTE_INTERVAL_SECONDS + 5)).isoformat(),
        )
        url = f"/api/admin/tracking/employee/{self.employee.id}/today-route/"
        r = self.admin_client.get(url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data["data"]["total_points"], 2)
        self.assertIn("polyline", r.data["data"])
        self.assertIn("route", r.data["data"])

    def test_admin_route_by_date(self):
        self._start_duty()
        self._update_location(12.9716, 77.5946)
        url = f"/api/admin/tracking/employee/{self.employee.id}/route/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["date"], str(self.today))
        self.assertGreaterEqual(r.data["data"]["total_points"], 1)

    def test_bulk_location_sync_throttled_and_partial_failure(self):
        self._start_duty()
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        t0 = timezone.now()
        r = self.client.post(
            "/api/tracking/location/bulk/",
            {
                "locations": [
                    {
                        "latitude": 12.9716,
                        "longitude": 77.5946,
                        "captured_at": t0.isoformat(),
                        "duty_session_id": duty.id,
                        "workday_id": duty.workday_id,
                        "battery_level": 80,
                    },
                    {
                        "latitude": 12.97161,
                        "longitude": 77.59461,
                        "captured_at": (t0 + timedelta(seconds=5)).isoformat(),
                    },
                    {
                        "latitude": 12.9750,
                        "longitude": 77.5980,
                        "captured_at": (t0 + timedelta(seconds=MIN_ROUTE_INTERVAL_SECONDS + 5)).isoformat(),
                    },
                    {
                        "latitude": "bad",
                        "longitude": 77.59,
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_207_MULTI_STATUS)
        data = r.data["data"]
        self.assertEqual(data["success_count"], 3)
        self.assertEqual(data["failed_count"], 1)
        self.assertEqual(len(data["failed_items"]), 1)
        self.assertEqual(data["failed_items"][0]["index"], 3)
        self.assertEqual(data["route_points_saved"], 2)
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                user=self.employee,
                point_type=EmployeeRoutePoint.POINT_GPS,
            ).count(),
            2,
        )
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertAlmostEqual(float(live.latitude), 12.9750, places=3)

    def test_bulk_location_v1_path_parity(self):
        self._start_duty()
        t0 = timezone.now()
        r = self.client.post(
            "/api/v1/tracking/location/bulk/",
            {
                "points": [
                    {
                        "latitude": 12.9716,
                        "longitude": 77.5946,
                        "timestamp": t0.isoformat(),
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["data"]["success_count"], 1)

    def test_bulk_location_requires_active_duty(self):
        r = self.client.post(
            "/api/tracking/location/bulk/",
            {
                "locations": [
                    {"latitude": 12.9716, "longitude": 77.5946},
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data.get("code"), "NO_ACTIVE_DUTY")

    def test_v1_tracking_paths_also_work(self):
        r = self.client.post(
            "/api/v1/tracking/duty/start/",
            {"latitude": 12.97, "longitude": 77.59},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        r2 = self.client.post(
            "/api/v1/tracking/location/update/",
            {"latitude": 12.9716, "longitude": 77.5946},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
