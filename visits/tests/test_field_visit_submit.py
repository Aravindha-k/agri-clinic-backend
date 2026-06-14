from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from mobile_api.test_helpers import login_mobile_client
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from visits.models import Visit
from visits.submitted import visit_has_field_visit_details, visit_has_submitted_details


class FieldVisitSubmitTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_fv",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(username="emp_fv", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-FV-01",
            phone="9000000888",
            is_active_employee=True,
        )
        district = District.objects.create(name="FV District")
        self.village = Village.objects.create(name="FV Village", district=district)
        self.farmer = Farmer.objects.create(
            name="FV Farmer",
            phone="9888777001",
            district=district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.category_pest, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "requires_problem_master": True},
        )
        self.category_others, _ = ProblemCategory.objects.get_or_create(
            code="others",
            defaults={"name": "Others", "requires_problem_master": False},
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category_pest,
            name="Stem borer",
            crop=self.crop,
        )
        self.field_visit_payload = {
            "farmer_name": "FV Farmer",
            "phone_number": "9888777001",
            "village_id": self.village.id,
            "crop_id": self.crop.id,
            "acreage": 2.5,
            "problem_category_id": self.category_pest.id,
            "problem_master_id": self.problem.id,
            "problem_description": "Visible stem damage on lower nodes.",
        }
        self.emp_client = login_mobile_client(employee_id="EMP-FV-01")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def test_mobile_field_visit_submit(self):
        before = Visit.objects.count()
        r = self.emp_client.post(
            "/api/v1/mobile/visits/",
            self.field_visit_payload,
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        visit = Visit.objects.latest("id")
        self.assertEqual(Visit.objects.count(), before + 1)
        self.assertTrue(visit_has_field_visit_details(visit))
        self.assertTrue(visit_has_submitted_details(visit))
        self.assertEqual(visit.land_area, 2.5)
        self.assertIsNone(visit.farmer_age)

    def test_field_visit_optional_age_when_sent(self):
        payload = dict(self.field_visit_payload)
        payload["age"] = 42
        r = self.emp_client.post("/api/v1/mobile/visits/", payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        visit = Visit.objects.latest("id")
        self.assertEqual(visit.farmer_age, 42)

    def test_others_category_without_master(self):
        payload = dict(self.field_visit_payload)
        payload["problem_category_id"] = self.category_others.id
        payload.pop("problem_master_id")
        r = self.emp_client.post("/api/v1/mobile/visits/", payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        visit = Visit.objects.latest("id")
        self.assertIsNone(visit.problem_master_id)

    def test_visit_form_options(self):
        r = self.emp_client.get("/api/v1/mobile/visit-form-options/")
        self.assertEqual(r.status_code, 200)
        data = r.data["data"]
        self.assertIn("villages", data)
        self.assertIn("problem_categories", data)

    def test_inline_farmer_create_on_visit(self):
        payload = dict(self.field_visit_payload)
        payload["farmer_name"] = "Brand New Farmer"
        payload["phone_number"] = "9111222333"
        payload.pop("farmer_id", None)
        before = Farmer.objects.filter(phone="9111222333").count()
        r = self.emp_client.post("/api/v1/mobile/visits/", payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Farmer.objects.filter(phone="9111222333").count(), before + 1)
        visit = Visit.objects.latest("id")
        self.assertIsNotNone(visit.farmer_id)

    def test_admin_create_field_visit(self):
        payload = dict(self.field_visit_payload)
        r = self.admin_client.post("/api/v1/admin/visits/", payload, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data.get("success"))
        self.assertIn("field_visit_snapshot", r.data["data"])

    def test_admin_payload_mobile_and_problem_id_alias(self):
        payload = {
            "farmer_name": "Alias Farmer",
            "mobile": "9888777666",
            "village_id": self.village.id,
            "crop_id": self.crop.id,
            "acreage": 1.0,
            "problem_id": self.category_pest.id,
            "problem_master_id": self.problem.id,
            "notes": "Damage noted in notes field.",
        }
        r = self.admin_client.post("/api/v1/admin/visits/", payload, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_missing_acreage_returns_field_error_not_generic(self):
        payload = dict(self.field_visit_payload)
        payload.pop("acreage")
        r = self.admin_client.post("/api/v1/admin/visits/", payload, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("acreage", str(r.data.get("message", "")).lower())
        self.assertNotIn(
            "Farmer name, phone, village",
            str(r.data.get("message", "")),
        )

    def test_problem_subcategory_dropdown_alias(self):
        r = self.emp_client.get(
            f"/api/v1/masters/problem-subcategories/dropdown/?category_id={self.category_pest.id}"
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("problem_subcategories", r.data["data"])

    def test_admin_problem_master_crud(self):
        r = self.admin_client.post(
            "/api/v1/admin/problem-masters/",
            {
                "category": self.category_pest.id,
                "name": "Leaf curl",
                "crop": self.crop.id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        master_id = r.data["id"]
        r2 = self.admin_client.get(f"/api/v1/admin/problem-masters/{master_id}/")
        self.assertEqual(r2.status_code, 200)
