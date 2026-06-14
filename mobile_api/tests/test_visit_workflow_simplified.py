"""Tests for simplified visit workflow (no required follow-up scheduling)."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from mobile_api.test_helpers import login_mobile_client
from visits.models import Visit
from visits.submitted import submitted_visits_qs


class SimplifiedVisitWorkflowTest(APITestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="simp_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-SIMP",
            phone="9000000777",
            is_active_employee=True,
        )
        self.client = login_mobile_client(employee_id="EMP-SIMP")

        self.district = District.objects.create(name="Simp D")
        self.village = Village.objects.create(name="Simp V", district=self.district)
        self.farmer = Farmer.objects.create(
            name="Simp Farmer",
            phone="9111222333",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_simp_test",
            defaults={
                "name": "Pest Test",
                "is_active": True,
                "requires_problem_master": True,
            },
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category,
            name="Aphids",
            crop=self.crop,
            is_active=True,
        )
        self.base = {
            "farmer": self.farmer.id,
            "crop": self.crop.id,
            "village": self.village.id,
            "latitude": 12.97,
            "longitude": 77.59,
            "farmer_name": self.farmer.name,
            "farmer_phone": self.farmer.phone,
            "land_area": 2.5,
            "problem_category": self.category.id,
            "problem_master": self.problem.id,
            "problem_description": "Leaves curling",
            "recommendation": "Spray neem oil weekly",
            "observation": "Moderate infestation on lower leaves",
        }

    def test_create_visit_without_follow_up_fields(self):
        r = self.client.post("/api/v1/mobile/visits/", self.base, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        visit = Visit.objects.get(pk=r.data["data"]["visit_id"])
        self.assertFalse(visit.follow_up_required)
        self.assertIsNone(visit.next_visit_date)
        self.assertEqual(visit.recommendation, "Spray neem oil weekly")
        self.assertEqual(visit.observation, "Moderate infestation on lower leaves")

    def test_create_revisit_for_existing_farmer(self):
        r1 = self.client.post("/api/v1/mobile/visits/", self.base, format="json")
        self.assertEqual(r1.status_code, 200)
        revisit = {
            **self.base,
            "recommendation": "Continue monitoring",
            "observation": "Improving after treatment",
            "problem_description": "Follow-up check",
        }
        r2 = self.client.post("/api/v1/mobile/visits/", revisit, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            submitted_visits_qs().filter(employee=self.employee, farmer=self.farmer).count(),
            2,
        )

    def test_farmer_detail_visit_summary_and_history(self):
        self.client.post("/api/v1/mobile/visits/", self.base, format="json")
        r = self.client.get(f"/api/v1/mobile/farmers/{self.farmer.id}/")
        self.assertEqual(r.status_code, 200)
        summary = r.data["data"]["visit_summary"]
        self.assertEqual(summary["visit_count"], 1)
        self.assertIsNotNone(summary["last_visit_date"])
        self.assertEqual(summary["latest_recommendation"], "Spray neem oil weekly")
        self.assertEqual(summary["latest_observation"], "Moderate infestation on lower leaves")
        history = r.data["data"]["visit_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["recommendation"], "Spray neem oil weekly")

    def test_visit_history_shows_previous_recommendation_after_revisit(self):
        self.client.post("/api/v1/mobile/visits/", self.base, format="json")
        self.client.post(
            "/api/v1/mobile/visits/",
            {**self.base, "recommendation": "Second advice", "observation": "Second obs"},
            format="json",
        )
        r = self.client.get(f"/api/v1/mobile/farmers/{self.farmer.id}/")
        history = r.data["data"]["visit_history"]
        self.assertEqual(len(history), 2)
        recs = {row["recommendation"] for row in history}
        self.assertIn("Spray neem oil weekly", recs)
        self.assertIn("Second advice", recs)

    def test_dashboard_does_not_depend_on_follow_up(self):
        today = timezone.localdate()
        Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            village=self.village,
            visit_date=today,
            latitude=12.97,
            longitude=77.59,
            land_area=2.5,
            problem_category=self.category,
            problem_master=self.problem,
            problem_description="Test",
            recommendation="Advice",
            follow_up_required=False,
        )
        r = self.client.get("/api/v1/mobile/dashboard/")
        self.assertEqual(r.status_code, 200)
        data = r.data["data"]
        self.assertIn("visits_today", data)
        self.assertIn("farmers_covered", data)
        self.assertIn("distance_today_km", data)
        self.assertIn("route_points_today", data)
        self.assertNotIn("follow_ups_due", data)
        self.assertNotIn("pending_follow_ups", data)
        self.assertGreaterEqual(data["visits_today"], 1)
        self.assertGreaterEqual(data["farmers_covered"], 1)

    def test_optional_follow_up_still_accepted_for_compat(self):
        payload = {
            **self.base,
            "follow_up_required": True,
            "follow_up_date": str(timezone.localdate() + timedelta(days=14)),
        }
        r = self.client.post("/api/v1/mobile/visits/", payload, format="json")
        self.assertEqual(r.status_code, 200)
        visit = Visit.objects.get(pk=r.data["data"]["visit_id"])
        self.assertTrue(visit.follow_up_required)
        self.assertIsNotNone(visit.next_visit_date)
