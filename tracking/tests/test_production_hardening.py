from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from mobile_api.test_helpers import login_mobile_client
from tracking.models import LocationLog, WorkDay
from tracking.route_utils import (
    apply_route_display,
    compute_route_distance_km,
    RouteDisplayOptions,
    simplify_route_uniform,
)
from tracking.selectors import _live_key
from tracking.workday_utils import expire_old_workdays


class RouteOptimizationTest(TestCase):
    def test_distance_ignores_gps_jump(self):
        route = [
            {"latitude": 12.0, "longitude": 77.0, "is_suspicious": False},
            {"latitude": 20.0, "longitude": 85.0, "is_suspicious": False},
        ]
        self.assertEqual(compute_route_distance_km(route), 0.0)

    def test_simplify_reduces_display_points(self):
        route = [
            {"latitude": i, "longitude": 77.0, "is_suspicious": False}
            for i in range(1000)
        ]
        display, meta = apply_route_display(
            route, RouteDisplayOptions(limit=50, simplify=True)
        )
        self.assertLessEqual(len(display), 50)
        self.assertEqual(meta["raw_point_count"], 1000)
        self.assertTrue(meta["simplified"])


class WorkdayIdempotentExpiryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="idem_wd", password="x")
        EmployeeProfile.objects.create(
            user=self.user,
            employee_id="IDEM-01",
            phone="9000000777",
            is_active_employee=True,
        )

    def test_expire_command_safe_to_run_twice(self):
        now = timezone.now()
        WorkDay.objects.create(
            user=self.user,
            date=now.date(),
            start_time=now - timedelta(hours=10),
            is_active=True,
        )
        self.assertEqual(expire_old_workdays(now=now), 1)
        self.assertEqual(expire_old_workdays(now=now), 0)
        call_command("expire_old_workdays")
        self.assertFalse(WorkDay.objects.filter(user=self.user, is_active=True).exists())

    def test_new_workday_after_auto_expiry(self):
        client = login_mobile_client(employee_id="IDEM-01")
        wd = WorkDay.objects.create(
            user=self.user,
            date=timezone.now().date(),
            start_time=timezone.now() - timedelta(hours=10),
            is_active=True,
        )
        cache.set(_live_key(self.user.pk), {"x": 1}, timeout=60)
        expire_old_workdays()
        wd.refresh_from_db()
        self.assertFalse(wd.is_active)
        r = client.post("/api/v1/tracking/workday/start/", {}, format="json")
        self.assertIn(r.status_code, (status.HTTP_201_CREATED, status.HTTP_200_OK))
        self.assertTrue(
            WorkDay.objects.filter(user=self.user, is_active=True).exists()
        )


class AdminRouteAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="harden_admin", password="x", is_staff=True, is_superuser=True
        )
        self.employee = User.objects.create_user(username="harden_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="HD-001",
            phone="9000000666",
            is_active_employee=True,
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def test_route_invalid_date_returns_400(self):
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {"date": "not-a-date"},
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_route_limit_and_simplify_params(self):
        wd = WorkDay.objects.create(
            user=self.employee,
            date=timezone.localdate(),
            start_time=timezone.now(),
            is_active=True,
        )
        t0 = timezone.now()
        for i in range(120):
            LocationLog.objects.create(
                user=self.employee,
                workday=wd,
                latitude=12.0 + i * 0.0001,
                longitude=77.0,
                recorded_at=t0 + timedelta(seconds=i),
            )
        r = self.admin_client.get(
            f"/api/v1/tracking/admin/employee/{self.employee.id}/route/",
            {
                "date": str(timezone.localdate()),
                "limit": "30",
                "simplify": "true",
            },
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["raw_point_count"], 120)
        self.assertLessEqual(data["display_point_count"], 30)
        self.assertTrue(data["simplified"])
        self.assertEqual(LocationLog.objects.filter(user=self.employee).count(), 120)
