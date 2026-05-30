from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from mobile_api.test_helpers import login_mobile_client
from visits.field_notes import NOT_ADDED_BY_EMPLOYEE
from visits.models import Visit
from visits.submitted import visit_has_submitted_details


class VisitFieldNotesFlowTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="notes_admin",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="notes_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="NOTES-01",
            phone="9000000555",
            is_active_employee=True,
        )
        district = District.objects.create(name="Notes District")
        village = Village.objects.create(name="Notes Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Notes Farmer",
            phone="9888777001",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(
            name_en="Tomato", name_ta="Tomato", is_active=True
        )
        self.emp_client = login_mobile_client(employee_id="NOTES-01")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _submit_payload(self, **extra):
        payload = {
            "farmer": self.farmer.id,
            "crop": self.crop.id,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "field_notes": "Leaf curl on lower branches.",
            "observation": "Leaf curl observed in 10% of plants.",
            "problem_seen": "Pest damage on leaves",
            "action_taken": "Advised neem spray",
            "follow_up_date": str(timezone.now().date()),
        }
        payload.update(extra)
        return payload

    def test_mobile_submit_saves_crop_and_field_notes(self):
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self._submit_payload(),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        visit_id = r.data["data"]["visit_id"]
        visit = Visit.objects.get(pk=visit_id)
        self.assertTrue(visit_has_submitted_details(visit))
        self.assertEqual(visit.crop_id, self.crop.id)
        self.assertIn("Leaf curl", visit.field_notes)
        self.assertIn("Pest damage", visit.problem_seen)

    def test_admin_sees_crop_and_field_notes(self):
        create = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self._submit_payload(),
            format="json",
        )
        visit_id = create.data["data"]["visit_id"]
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        row = r.data
        self.assertIsNotNone(row.get("crop_info") or row.get("crop"))
        crop_name = row.get("crop_name") or (row.get("crop") or {}).get("name_en")
        self.assertIn("Tomato", crop_name or "")
        self.assertIn("Leaf curl", row["field_notes"])
        self.assertIn("Pest damage", row["problem_seen"])

    def test_missing_notes_shows_not_added_message(self):
        Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
        )
        r = self.admin_client.get("/api/v1/admin/visits/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        row = r.data["results"][0]
        self.assertEqual(row["field_notes"], NOT_ADDED_BY_EMPLOYEE)
        self.assertEqual(row["observation"], NOT_ADDED_BY_EMPLOYEE)

    def test_legacy_advice_maps_to_field_notes_in_response(self):
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
            general_advice="Apply NPK after rain",
        )
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertIn("NPK", r.data["field_notes"])
