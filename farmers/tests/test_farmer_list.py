from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from masters.models import District, Farmer, Village
from visits.models import Visit


class FarmerListAPITest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_farmer_list",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="emp_farmer_list", password="x")
        self.client = APIClient()

        district = District.objects.create(name="Audit District")
        village = Village.objects.create(name="Audit Village", district=district)

        self.zero_visits = Farmer.objects.create(
            name="Zero Visits Farmer",
            phone="9111111111",
            district=district,
            village=village,
        )
        self.with_visit = Farmer.objects.create(
            name="With Visit Farmer",
            phone="9222222222",
            district=district,
            village=village,
        )
        self.admin_created = Farmer.objects.create(
            name="Admin Created Farmer",
            phone="9333333333",
            district=district,
            village=village,
            is_active=False,
        )

        Visit.objects.create(
            employee=self.admin,
            farmer=self.with_visit,
            farmer_name=self.with_visit.name,
            farmer_phone=self.with_visit.phone,
            village=village,
            status="pending",
        )

    def test_list_returns_all_farmers(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/farmers/", {"page_size": 100})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.admin_created.id, ids)
        self.assertIn(self.zero_visits.id, ids)

    def test_employee_sees_admin_created_farmer(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.get("/api/v1/farmers/", {"page_size": 100})
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.admin_created.id, ids)

    def test_list_fields_no_status_flags(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/farmers/", {"page_size": 5})
        row = next(r for r in response.data["results"] if r["id"] == self.with_visit.id)
        for key in (
            "id",
            "name",
            "phone",
            "mobile",
            "village",
            "crop_name",
            "total_visits",
        ):
            self.assertIn(key, row)
        self.assertNotIn("is_active", row)
