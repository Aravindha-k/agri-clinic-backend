from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from mobile_api.test_helpers import login_mobile_client
from visits.models import Visit
from visits.submitted import visit_has_submitted_details


class VisitReleaseBlockerTest(APITestCase):
    """P0 release blockers: multipart booleans + recommendation/observation persistence."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="blocker_admin",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="blocker_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="BLOCKER-01",
            phone="9000000666",
            is_active_employee=True,
        )
        district = District.objects.create(name="Blocker District")
        self.village = Village.objects.create(name="Blocker Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Blocker Farmer",
            phone="9888777666",
            district=district,
            village=self.village,
        )
        self.crop = Crop.objects.create(
            name_en="Tomato", name_ta="Tomato", is_active=True
        )
        self.category_pest, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "requires_problem_master": True},
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category_pest,
            name="Leaf curl",
            crop=self.crop,
        )
        self.emp_client = login_mobile_client(employee_id="BLOCKER-01")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _base_payload(self, **extra):
        payload = {
            "farmer_id": self.farmer.id,
            "farmer_name": self.farmer.name,
            "farmer_phone": self.farmer.phone,
            "village_id": self.village.id,
            "crop_id": self.crop.id,
            "acreage": 2.5,
            "problem_category_id": self.category_pest.id,
            "problem_master_id": self.problem.id,
            "problem_description": "Pest damage on leaves",
            "problem_seen": "Pest damage on leaves",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "observation": "Yellow leaves on lower branches during field walk.",
            "recommendation": "Apply neem spray in the evening.",
            "action_taken": "Demonstrated spray technique to farmer.",
            "fertilizer_advice": "20kg DAP per acre next week.",
            "pesticide_advice": "Neem 5% weekly for 2 weeks.",
            "irrigation_advice": "Light irrigation every 3 days.",
            "general_advice": "Monitor lower leaves for 7 days.",
            "follow_up_date": str(timezone.now().date()),
        }
        payload.update(extra)
        return payload

    def _visit_id_from_response(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["data"]["visit_id"]

    def test_multipart_submit_follow_up_true_string(self):
        payload = self._base_payload(follow_up_required="true")
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            payload,
            format="multipart",
        )
        visit_id = self._visit_id_from_response(r)
        visit = Visit.objects.get(pk=visit_id)
        self.assertTrue(visit.follow_up_required)
        self.assertEqual(visit.recommendation, "Apply neem spray in the evening.")
        self.assertIn("Yellow leaves", visit.observation)

    def test_multipart_submit_follow_up_false_string(self):
        payload = self._base_payload(follow_up_required="false")
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            payload,
            format="multipart",
        )
        visit_id = self._visit_id_from_response(r)
        visit = Visit.objects.get(pk=visit_id)
        self.assertFalse(visit.follow_up_required)

    def test_json_submit_follow_up_true(self):
        payload = self._base_payload(follow_up_required=True)
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            payload,
            format="json",
        )
        visit_id = self._visit_id_from_response(r)
        visit = Visit.objects.get(pk=visit_id)
        self.assertTrue(visit.follow_up_required)

    def test_recommendation_and_observation_both_persist(self):
        payload = self._base_payload()
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            payload,
            format="json",
        )
        visit_id = self._visit_id_from_response(r)
        visit = Visit.objects.get(pk=visit_id)
        self.assertTrue(visit_has_submitted_details(visit))
        self.assertEqual(visit.recommendation, "Apply neem spray in the evening.")
        self.assertIn("Yellow leaves", visit.observation)
        self.assertEqual(visit.action_taken, "Demonstrated spray technique to farmer.")
        self.assertEqual(visit.fertilizer_advice, "20kg DAP per acre next week.")
        self.assertEqual(visit.pesticide_advice, "Neem 5% weekly for 2 weeks.")
        self.assertEqual(visit.irrigation_advice, "Light irrigation every 3 days.")
        self.assertEqual(visit.general_advice, "Monitor lower leaves for 7 days.")

    def test_admin_visit_detail_returns_recommendation(self):
        create = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self._base_payload(follow_up_required=True),
            format="json",
        )
        visit_id = self._visit_id_from_response(create)
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("Apply neem spray", r.data["recommendation"])
        self.assertIn("Yellow leaves", r.data["observation"])

    def test_farmer_visit_history_returns_recommendation_for_revisit_prefill(self):
        create = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self._base_payload(follow_up_required=True),
            format="json",
        )
        visit_id = self._visit_id_from_response(create)
        r = self.emp_client.get(f"/api/v1/farmers/{self.farmer.id}/visits/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        rows = r.data.get("results") or r.data
        match = next(row for row in rows if row["id"] == visit_id)
        self.assertIn("Apply neem spray", match["recommendation"])
        self.assertIn("Yellow leaves", match["observation"])

    def test_multipart_invalid_follow_up_required_returns_400_not_500(self):
        payload = self._base_payload(follow_up_required="maybe")
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            payload,
            format="multipart",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotEqual(r.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
