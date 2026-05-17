from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE, visit_has_submitted_details


class VisitSubmitOnlyCreationTest(TestCase):
    """Visits are persisted only on full submit (farmer + crop + GPS)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_submit",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="emp_submit", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-SUBMIT-01",
            phone="9000000999",
            is_active_employee=True,
        )
        district = District.objects.create(name="Submit District")
        village = Village.objects.create(name="Submit Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Submit Farmer",
            phone="9888777666",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Maize", name_ta="Maize", is_active=True)
        self.complete_payload = {
            "farmer": self.farmer.id,
            "crop": self.crop.id,
            "latitude": 12.9716,
            "longitude": 77.5946,
        }
        self.emp_client = APIClient()
        self.emp_client.force_authenticate(user=self.employee)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def test_incomplete_mobile_post_does_not_create_row(self):
        before = Visit.objects.count()
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            {"farmer": self.farmer.id},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.data["success"])
        self.assertEqual(r.data["message"], SUBMIT_VISIT_REQUIRED_MESSAGE)
        self.assertEqual(Visit.objects.count(), before)

    def test_incomplete_admin_post_does_not_create_row(self):
        before = Visit.objects.count()
        r = self.admin_client.post(
            "/api/v1/visits/",
            {"crop": self.crop.id, "latitude": 12.0, "longitude": 77.0},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.data["success"])
        self.assertEqual(r.data["message"], SUBMIT_VISIT_REQUIRED_MESSAGE)
        self.assertEqual(Visit.objects.count(), before)

    def test_complete_mobile_post_creates_row(self):
        before = Visit.objects.count()
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self.complete_payload,
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        visit = Visit.objects.get(pk=r.data["data"]["visit_id"])
        self.assertTrue(visit_has_submitted_details(visit))
        self.assertEqual(Visit.objects.count(), before + 1)

    def test_complete_admin_post_creates_row(self):
        before = Visit.objects.count()
        r = self.admin_client.post(
            "/api/v1/visits/",
            self.complete_payload,
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Visit.objects.count(), before + 1)
        visit = Visit.objects.latest("id")
        self.assertTrue(visit_has_submitted_details(visit))

    def test_start_visit_endpoint_does_not_create_row(self):
        before = Visit.objects.count()
        r = self.emp_client.post(
            "/api/v1/visits/start/",
            {
                "crop": self.crop.id,
                "latitude": "12.971600",
                "longitude": "77.594600",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 410)
        self.assertEqual(Visit.objects.count(), before)
