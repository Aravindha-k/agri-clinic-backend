"""Admin visits start_date/end_date filter contract."""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit


class AdminVisitDateFilterTests(APITestCase):
    url = "/api/v1/admin/visits/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_date_filter",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.emp = User.objects.create_user(username="emp_date", password="x")
        EmployeeProfile.objects.create(
            user=self.emp,
            employee_id="EMP-DATE",
            phone="9000000999",
            is_active_employee=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        self.district = District.objects.create(name="Date District")
        village = Village.objects.create(name="Date Village", district=self.district)
        self.farmer = Farmer.objects.create(
            name="Date Farmer",
            phone="9111000111",
            district=self.district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.today = timezone.localdate()
        self.week_ago = self.today - timedelta(days=7)
        self.month_ago = self.today - timedelta(days=40)

        self.v_today = self._visit(self.today, farmer_name="Today Visit")
        self.v_week = self._visit(self.week_ago, farmer_name="Week Visit")
        self.v_old = self._visit(self.month_ago, farmer_name="Old Visit")
        self.v_null_date = self._visit(self.today, farmer_name="NullDate Visit")
        Visit.objects.filter(pk=self.v_null_date.pk).update(
            visit_date=None, created_at=timezone.now()
        )
        self.v_null_date.refresh_from_db()

    def _visit(self, visit_date, *, farmer_name="F"):
        return Visit.objects.create(
            employee=self.emp,
            farmer=self.farmer,
            farmer_name=farmer_name,
            crop=self.crop,
            latitude=11.0,
            longitude=78.0,
            district=self.district,
            visit_date=visit_date or self.today,
        )

    def _ids(self, params=None):
        r = self.client.get(self.url, params or {})
        self.assertEqual(r.status_code, 200, r.data)
        return {row["id"] for row in r.data["results"]}

    def test_range_inclusive(self):
        ids = self._ids(
            {
                "start_date": self.week_ago.isoformat(),
                "end_date": self.today.isoformat(),
                "page_size": 100,
            }
        )
        self.assertIn(self.v_today.id, ids)
        self.assertIn(self.v_week.id, ids)
        self.assertNotIn(self.v_old.id, ids)

    def test_same_day_range(self):
        ids = self._ids(
            {
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
                "page_size": 100,
            }
        )
        self.assertIn(self.v_today.id, ids)
        self.assertNotIn(self.v_week.id, ids)
        self.assertNotIn(self.v_old.id, ids)

    def test_start_only(self):
        ids = self._ids({"start_date": self.today.isoformat(), "page_size": 100})
        self.assertIn(self.v_today.id, ids)
        self.assertNotIn(self.v_old.id, ids)

    def test_end_only(self):
        ids = self._ids({"end_date": self.week_ago.isoformat(), "page_size": 100})
        self.assertIn(self.v_week.id, ids)
        self.assertIn(self.v_old.id, ids)
        self.assertNotIn(self.v_today.id, ids)

    def test_search_plus_range(self):
        ids = self._ids(
            {
                "start_date": self.week_ago.isoformat(),
                "end_date": self.today.isoformat(),
                "search": "Week Visit",
                "page_size": 100,
            }
        )
        self.assertEqual(ids, {self.v_week.id})

    def test_pagination_with_range_count(self):
        r = self.client.get(
            self.url,
            {
                "start_date": self.week_ago.isoformat(),
                "end_date": self.today.isoformat(),
                "page_size": 1,
            },
        )
        self.assertEqual(r.status_code, 200)
        # today + week + null-date fallback (today) = at least 2
        self.assertGreaterEqual(r.data["count"], 2)
        self.assertEqual(len(r.data["results"]), 1)

    def test_no_results(self):
        far = (self.today + timedelta(days=30)).isoformat()
        ids = self._ids({"start_date": far, "end_date": far, "page_size": 100})
        self.assertEqual(ids, set())

    def test_invalid_date_400(self):
        r = self.client.get(self.url, {"start_date": "14-08-2026"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.data.get("success", True) if isinstance(r.data, dict) else True)

    def test_null_visit_date_uses_created_at_fallback(self):
        ids = self._ids(
            {
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
                "page_size": 100,
            }
        )
        self.assertIn(self.v_null_date.id, ids)
