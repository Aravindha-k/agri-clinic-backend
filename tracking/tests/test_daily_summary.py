from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from tracking.daily_summary import (
    DailySummaryService,
    build_employee_daily_summary,
    build_visit_stops,
    compute_idle_minutes,
    compute_work_hours_seconds,
)
from tracking.models import LocationLog, WorkDay
from visits.models import Visit


class DailySummaryServiceTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="ds_admin",
            password="x",
            is_staff=True,
        )
        self.employee = User.objects.create_user(username="ds_emp", password="x")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="DS-001",
            phone="9000000333",
            is_active_employee=True,
        )
        self.district = District.objects.create(name="DS District")
        self.village_a = Village.objects.create(name="Village A", district=self.district)
        self.village_b = Village.objects.create(name="Village B", district=self.district)
        self.farmer_a = Farmer.objects.create(
            name="Farmer A",
            phone="9111111111",
            district=self.district,
            village=self.village_a,
        )
        self.farmer_b = Farmer.objects.create(
            name="Farmer B",
            phone="9222222222",
            district=self.district,
            village=self.village_b,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.today = timezone.localdate()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _create_workday(self, *, hours_ago_start=2, ended=False):
        start = timezone.now() - timedelta(hours=hours_ago_start)
        end = timezone.now() - timedelta(hours=1) if ended else None
        return WorkDay.objects.create(
            user=self.employee,
            date=self.today,
            start_time=start,
            end_time=end,
            is_active=not ended,
            last_heartbeat=timezone.now(),
        )

    def _create_submitted_visit(self, *, farmer, village, hour, minute=0):
        visit_time = timezone.now().replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ).time()
        return Visit.objects.create(
            employee=self.employee,
            visit_date=self.today,
            visit_time=visit_time,
            farmer=farmer,
            farmer_name=farmer.name,
            farmer_phone=farmer.phone,
            village=village,
            crop=self.crop,
            latitude=12.97 + hour * 0.001,
            longitude=77.59 + hour * 0.001,
        )

    def test_compute_work_hours_seconds_ended_workday(self):
        wd = self._create_workday(hours_ago_start=3, ended=True)
        seconds = compute_work_hours_seconds([wd], self.today)
        self.assertGreater(seconds, 0)
        self.assertLessEqual(seconds, 3 * 3600 + 60)

    def test_compute_idle_minutes_low_movement_segments(self):
        t0 = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        route = [
            {
                "latitude": 12.97,
                "longitude": 77.59,
                "recorded_at": t0.isoformat(),
            },
            {
                "latitude": 12.97001,
                "longitude": 77.59001,
                "recorded_at": (t0 + timedelta(minutes=15)).isoformat(),
            },
            {
                "latitude": 12.98,
                "longitude": 77.60,
                "recorded_at": (t0 + timedelta(minutes=20)).isoformat(),
            },
        ]
        idle = compute_idle_minutes(route)
        self.assertGreaterEqual(idle, 14)

    def test_build_visit_stops_chronological(self):
        self._create_submitted_visit(farmer=self.farmer_a, village=self.village_a, hour=10)
        self._create_submitted_visit(farmer=self.farmer_b, village=self.village_b, hour=9)
        stops = build_visit_stops(self.employee.id, self.today)
        self.assertEqual(len(stops), 2)
        self.assertEqual(stops[0]["farmer_name"], "Farmer B")
        self.assertEqual(stops[1]["farmer_name"], "Farmer A")
        self.assertEqual(stops[0]["type"], "visit")

    def test_build_employee_daily_summary_aggregates_metrics(self):
        wd = self._create_workday(hours_ago_start=4, ended=True)
        t0 = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.97,
            longitude=77.59,
            recorded_at=t0,
        )
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.98,
            longitude=77.60,
            recorded_at=t0 + timedelta(minutes=30),
        )
        self._create_submitted_visit(farmer=self.farmer_a, village=self.village_a, hour=10)
        self._create_submitted_visit(farmer=self.farmer_b, village=self.village_b, hour=11)

        summary = build_employee_daily_summary(
            user_id=self.employee.id,
            employee_id=self.profile.employee_id,
            target_date=self.today,
        )
        self.assertEqual(summary["employee_id"], "DS-001")
        self.assertEqual(summary["visits_completed"], 2)
        self.assertEqual(summary["farmers_covered"], 2)
        self.assertEqual(summary["villages_covered"], 2)
        self.assertGreater(summary["work_hours_seconds"], 0)
        self.assertGreater(summary["distance_km"], 0)
        self.assertIn("h", summary["work_hours"])

    def test_daily_summary_service_wrapper(self):
        summary = DailySummaryService.for_employee(
            self.employee,
            employee_id=self.profile.employee_id,
            target_date=self.today,
        )
        self.assertEqual(summary["visits_completed"], 0)
        self.assertEqual(summary["idle_minutes"], 0)

    def test_admin_daily_summary_api(self):
        wd = self._create_workday(hours_ago_start=2, ended=True)
        t0 = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.96,
            longitude=77.58,
            recorded_at=t0,
        )
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.97,
            longitude=77.59,
            recorded_at=t0 + timedelta(minutes=10),
        )
        self._create_submitted_visit(farmer=self.farmer_a, village=self.village_a, hour=9)

        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/daily-summary/",
            {"date": str(self.today)},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["success"])
        data = r.data["data"]
        self.assertEqual(data["visits_completed"], 1)
        self.assertEqual(data["farmers_covered"], 1)
        self.assertEqual(data["villages_covered"], 1)
        self.assertIn("work_hours", data)
        self.assertIn("distance_travelled_km", data)
        self.assertIn("idle_minutes", data)

    def test_admin_daily_summary_requires_admin(self):
        client = APIClient()
        client.force_authenticate(user=self.employee)
        r = client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/daily-summary/",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_daily_summary_invalid_date(self):
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/daily-summary/",
            {"date": "not-a-date"},
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_route_includes_visit_stops(self):
        wd = self._create_workday()
        t0 = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        LocationLog.objects.create(
            user=self.employee,
            workday=wd,
            latitude=12.97,
            longitude=77.59,
            recorded_at=t0,
        )
        visit = self._create_submitted_visit(
            farmer=self.farmer_a, village=self.village_a, hour=10
        )

        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {"date": str(self.today)},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        stops = r.data["data"]["stops"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["visit_id"], visit.id)
        self.assertEqual(stops[0]["farmer_name"], "Farmer A")
        self.assertEqual(stops[0]["village_name"], "Village A")
        self.assertIsNotNone(stops[0]["timestamp"])
        self.assertIn("polyline", r.data["data"])
