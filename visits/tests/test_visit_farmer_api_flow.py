from django.contrib.auth.models import User
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from mobile_api.test_helpers import login_mobile_client
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit
from visits.submitted import visit_has_submitted_details


class VisitFarmerAPIFlowTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_flow", password="x", is_staff=True, is_superuser=True
        )
        self.employee = User.objects.create_user(username="emp_flow", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-FLOW-01",
            phone="9000000100",
            is_active_employee=True,
        )
        self.emp_client = login_mobile_client(employee_id="EMP-FLOW-01")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

        district = District.objects.create(name="Flow District")
        village = Village.objects.create(name="Flow Village", district=district)
        self.admin_farmer = Farmer.objects.create(
            name="Admin Created Farmer",
            phone="9111000001",
            district=district,
            village=village,
            is_active=False,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)

    def _submitted_payload(self, farmer_id):
        return {
            "farmer": farmer_id,
            "crop": self.crop.id,
            "latitude": 12.97,
            "longitude": 77.59,
        }

    def test_farmers_list_shows_all_including_admin_created(self):
        r = self.emp_client.get("/api/v1/farmers/", {"page_size": 100})
        self.assertEqual(r.status_code, 200)
        ids = {row["id"] for row in r.data["results"]}
        self.assertIn(self.admin_farmer.id, ids)
        self.assertNotIn("is_active", r.data["results"][0])

    def test_mobile_farmers_list_matches_directory(self):
        r = self.emp_client.get("/api/v1/mobile/farmers/", {"page_size": 100})
        self.assertEqual(r.status_code, 200)
        ids = {row["id"] for row in r.data["results"]}
        self.assertIn(self.admin_farmer.id, ids)

    def test_admin_farmers_list_all_records(self):
        r = self.admin_client.get("/api/v1/admin/farmers/", {"page_size": 100})
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data["results"]), 1)

    def test_mobile_visit_submit_appears_in_lists_without_status_field(self):
        create = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self._submitted_payload(self.admin_farmer.id),
            format="json",
        )
        self.assertEqual(create.status_code, 200)
        visit_id = create.data["data"]["visit_id"]
        visit = Visit.objects.get(pk=visit_id)
        self.assertTrue(visit_has_submitted_details(visit))

        mobile_list = self.emp_client.get("/api/v1/mobile/visits/")
        self.assertEqual(mobile_list.status_code, 200)
        self.assertTrue(any(v["id"] == visit_id for v in mobile_list.data["data"]))
        self.assertNotIn("status", mobile_list.data["data"][0])

        admin_list = self.admin_client.get("/api/v1/admin/visits/")
        results = admin_list.data["results"]
        self.assertEqual(len(results), 1)
        self.assertNotIn("status", results[0])
        self.assertIn("farmer_name", results[0])

    def test_incomplete_visit_hidden_from_lists(self):
        Visit.objects.create(
            employee=self.employee,
            farmer=self.admin_farmer,
            farmer_name=self.admin_farmer.name,
            status="pending",
        )
        r = self.admin_client.get("/api/v1/admin/visits/")
        self.assertEqual(len(r.data["results"]), 0)

    def test_visits_list_ignores_legacy_status_query_param(self):
        Visit.objects.create(
            employee=self.employee,
            farmer=self.admin_farmer,
            crop=self.crop,
            latitude=1.0,
            longitude=2.0,
            farmer_name=self.admin_farmer.name,
            status="pending",
        )
        r = self.admin_client.get("/api/v1/visits/", {"status": "cancelled"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)

    def test_visit_response_includes_farmer_block(self):
        self.emp_client.post(
            "/api/v1/mobile/visits/",
            self._submitted_payload(self.admin_farmer.id),
            format="json",
        )
        r = self.emp_client.get("/api/v1/mobile/visits/")
        row = r.data["data"][0]
        farmer = row.get("farmer") or {}
        self.assertIn("mobile", farmer)
        self.assertIn("village", farmer)
        self.assertIn("crop_name", farmer)
