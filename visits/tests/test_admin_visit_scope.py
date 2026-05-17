from django.contrib.auth.models import User
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit
from visits.submitted import visit_has_submitted_details


class AdminVisitScopeTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_visits", password="x", is_staff=True, is_superuser=True
        )
        self.emp_a = User.objects.create_user(username="emp_a", password="x")
        self.emp_b = User.objects.create_user(username="emp_b", password="x")
        for user, eid in ((self.emp_a, "EMP-A"), (self.emp_b, "EMP-B")):
            EmployeeProfile.objects.create(
                user=user,
                employee_id=eid,
                phone=f"9000000{eid[-1]}",
                is_active_employee=True,
            )

        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.emp_a)
        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.emp_b)

        district = District.objects.create(name="Scope District")
        village = Village.objects.create(name="Scope Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Scope Farmer",
            phone="9111222333",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Maize", name_ta="Maize", is_active=True)

    def _payload(self):
        return {
            "farmer": self.farmer.id,
            "crop": self.crop.id,
            "latitude": 12.97,
            "longitude": 77.59,
        }

    def test_admin_list_returns_both_employees_submitted_visits(self):
        r_a = self.client_a.post("/api/v1/mobile/visits/", self._payload(), format="json")
        r_b = self.client_b.post("/api/v1/mobile/visits/", self._payload(), format="json")
        self.assertEqual(r_a.status_code, 200)
        self.assertEqual(r_b.status_code, 200)
        id_a = r_a.data["data"]["visit_id"]
        id_b = r_b.data["data"]["visit_id"]

        admin = self.admin_client.get("/api/v1/admin/visits/", {"page_size": 100})
        self.assertEqual(admin.status_code, 200)
        ids = {row["id"] for row in admin.data["results"]}
        self.assertIn(id_a, ids)
        self.assertIn(id_b, ids)
        self.assertNotIn("status", admin.data["results"][0])

    def test_mobile_lists_are_employee_scoped(self):
        self.client_a.post("/api/v1/mobile/visits/", self._payload(), format="json")
        self.client_b.post("/api/v1/mobile/visits/", self._payload(), format="json")

        list_a = self.client_a.get("/api/v1/mobile/visits/")
        list_b = self.client_b.get("/api/v1/mobile/visits/")
        self.assertEqual(len(list_a.data["data"]), 1)
        self.assertEqual(len(list_b.data["data"]), 1)
        self.assertEqual(list_a.data["data"][0]["employee"], self.emp_a.id)
        self.assertEqual(list_b.data["data"][0]["employee"], self.emp_b.id)

    def test_incomplete_visit_excluded_from_admin_list(self):
        Visit.objects.create(
            employee=self.emp_a,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
        )
        r = self.admin_client.get("/api/v1/admin/visits/")
        self.assertEqual(r.data["count"], 0)

    def test_status_query_param_ignored_on_visits_list(self):
        Visit.objects.create(
            employee=self.emp_a,
            farmer=self.farmer,
            crop=self.crop,
            latitude=1.0,
            longitude=2.0,
            farmer_name=self.farmer.name,
            status="pending",
        )
        r = self.admin_client.get("/api/v1/visits/", {"status": "pending"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        visit = Visit.objects.get(pk=r.data["results"][0]["id"])
        self.assertTrue(visit_has_submitted_details(visit))
