from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    CropProblem,
    District,
    Farmer,
    ProblemCategory,
    ProblemMaster,
    Village,
)
from mobile_api.test_helpers import assign_operational_territory, login_mobile_client
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
        assign_operational_territory(self.employee, village)
        self.village = village
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
            "village": self.village.id,
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

    # Tests 24-29: Historical preservation (RULE B)
    def test_old_visit_fk_to_inactive_problem_master_still_displays(self):
        """Test 24: old Visit FK to inactive ProblemMaster still displays."""
        pest_cat = ProblemCategory.objects.get_or_create(
            code=ProblemCategory.CODE_PEST,
            defaults={"name": "Pest", "is_active": True},
        )[0]
        pest = ProblemMaster.objects.create(
            category=pest_cat,
            name="Old Pest",
            is_active=True,
        )
        
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
            problem_category=pest_cat,
            problem_master=pest,
        )
        
        # Deactivate the master
        pest.is_active = False
        pest.save(update_fields=["is_active"])
        
        # Visit detail should still show the inactive master
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # Check that problem is displayed
        problems = r.data.get("problems", r.data.get("field_visit", {}).get("problems", []))
        problem_ids = {p.get("id") for p in problems}
        self.assertIn(pest.id, problem_ids)

    def test_old_visit_m2m_containing_inactive_problem_master_still_displays(self):
        """Test 25: old Visit M2M containing inactive ProblemMaster still displays."""
        pest_cat = ProblemCategory.objects.get_or_create(
            code=ProblemCategory.CODE_PEST,
            defaults={"name": "Pest", "is_active": True},
        )[0]
        pest_active = ProblemMaster.objects.create(
            category=pest_cat,
            name="Active Pest",
            is_active=True,
        )
        pest_inactive = ProblemMaster.objects.create(
            category=pest_cat,
            name="Inactive Pest",
            is_active=True,
        )
        
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
        )
        visit.problem_items.set([pest_active, pest_inactive])
        
        # Deactivate one master
        pest_inactive.is_active = False
        pest_inactive.save(update_fields=["is_active"])
        
        # Visit detail should show BOTH problems
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        problems = r.data.get("problems", r.data.get("field_visit", {}).get("problems", []))
        problem_ids = {p.get("id") for p in problems}
        self.assertIn(pest_active.id, problem_ids)
        self.assertIn(pest_inactive.id, problem_ids)

    def test_visit_with_active_and_inactive_problem_items_displays_both(self):
        """Test 26: Visit with active + inactive problem_items displays BOTH."""
        pest_cat = ProblemCategory.objects.get_or_create(
            code=ProblemCategory.CODE_PEST,
            defaults={"name": "Pest", "is_active": True},
        )[0]
        pest_active = ProblemMaster.objects.create(
            category=pest_cat,
            name="Active Pest",
            is_active=True,
        )
        pest_inactive = ProblemMaster.objects.create(
            category=pest_cat,
            name="Inactive Pest",
            is_active=True,
        )
        
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
        )
        visit.problem_items.set([pest_active, pest_inactive])
        
        # Deactivate one
        pest_inactive.is_active = False
        pest_inactive.save(update_fields=["is_active"])
        
        # Should display both
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        problems = r.data.get("problems", r.data.get("field_visit", {}).get("problems", []))
        self.assertEqual(len(problems), 2)

    def test_old_visit_referencing_inactive_crop_still_displays_crop(self):
        """Test 27: old Visit referencing inactive Crop still displays Crop."""
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
        )
        
        # Deactivate crop
        self.crop.is_active = False
        self.crop.save(update_fields=["is_active"])
        
        # Visit detail should still show the crop
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        crop_info = r.data.get("crop_info") or r.data.get("crop")
        self.assertIsNotNone(crop_info)
        self.assertEqual(crop_info.get("id"), self.crop.id)

    def test_historical_read_does_not_reactivate_anything(self):
        """Test 28: historical read does not reactivate anything."""
        pest_cat = ProblemCategory.objects.get_or_create(
            code=ProblemCategory.CODE_PEST,
            defaults={"name": "Pest", "is_active": True},
        )[0]
        pest = ProblemMaster.objects.create(
            category=pest_cat,
            name="Inactive Pest",
            is_active=False,
        )
        
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
            problem_category=pest_cat,
            problem_master=pest,
        )
        
        # Read visit
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        
        # Master should still be inactive
        pest.refresh_from_db()
        self.assertFalse(pest.is_active)

    def test_deactivating_master_does_not_modify_visit_records(self):
        """Test 29: deactivating master does not modify Visit records."""
        pest_cat = ProblemCategory.objects.get_or_create(
            code=ProblemCategory.CODE_PEST,
            defaults={"name": "Pest", "is_active": True},
        )[0]
        pest = ProblemMaster.objects.create(
            category=pest_cat,
            name="Active Pest",
            is_active=True,
        )
        
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            visit_date=timezone.now().date(),
            problem_category=pest_cat,
            problem_master=pest,
        )
        visit.problem_items.set([pest])
        
        # Record initial state
        initial_problem_master_id = visit.problem_master_id
        initial_problem_items_count = visit.problem_items.count()
        
        # Deactivate master
        pest.is_active = False
        pest.save(update_fields=["is_active"])
        
        # Refresh visit
        visit.refresh_from_db()
        
        # Visit records should be unchanged
        self.assertEqual(visit.problem_master_id, initial_problem_master_id)
        self.assertEqual(visit.problem_items.count(), initial_problem_items_count)
