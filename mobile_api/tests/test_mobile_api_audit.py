from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

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
from visits.models import Visit
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE


class MobileAPIAuditTest(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="mob_audit", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-AUDIT",
            phone="9000000888",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="admin_audit", password="x", is_staff=True, is_superuser=True
        )
        self.client = login_mobile_client(employee_id="EMP-AUDIT", password="x")

        district = District.objects.create(name="Audit D")
        village = Village.objects.create(name="Audit V", district=district)
        assign_operational_territory(self.employee, village)
        self.farmer = Farmer.objects.create(
            name="Audit Farmer",
            phone="9777666555",
            district=district,
            village=village,
        )
        self.crop_a = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.crop_b = Crop.objects.create(name_en="Wheat", name_ta="Wheat", is_active=True)
        
        # Create categories
        self.pest_cat = ProblemCategory.objects.create(
            code=ProblemCategory.CODE_PEST,
            name="Pest",
            is_active=True,
        )
        self.disease_cat = ProblemCategory.objects.create(
            code=ProblemCategory.CODE_DISEASE,
            name="Disease",
            is_active=True,
        )
        
        # Create masters
        self.pest_a1 = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Aphid",
            is_active=True,
        )
        self.pest_a2 = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Stem Borer",
            is_active=True,
        )
        self.disease_a = ProblemMaster.objects.create(
            category=self.disease_cat,
            name="Blast",
            is_active=True,
        )
        
        # Create global unmapped master (should be excluded in strict mode)
        self.global_pest = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Global Pest",
            is_active=True,
        )
        
        # Create legacy crop-FK-only master (should be excluded in strict mode)
        self.legacy_pest = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Legacy FK Pest",
            crop=self.crop_a,
            is_active=True,
        )
        
        # Create master for other crop (should be excluded in strict mode)
        self.other_crop_pest = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Other Crop Pest",
            is_active=True,
        )
        CropProblem.objects.create(crop=self.crop_b, problem_master=self.other_crop_pest)
        
        # Create inactive master (should be excluded)
        self.inactive_pest = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Inactive Pest",
            is_active=False,
        )
        
        # Map masters to crop_a
        CropProblem.objects.create(crop=self.crop_a, problem_master=self.pest_a1)
        CropProblem.objects.create(crop=self.crop_a, problem_master=self.pest_a2)
        CropProblem.objects.create(crop=self.crop_a, problem_master=self.disease_a)
        
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_audit_test",
            defaults={
                "name": "Pest Audit",
                "is_active": True,
                "requires_problem_master": True,
            },
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category,
            name="Aphids",
            crop=self.crop_a,
            is_active=True,
        )
        self.payload = {
            "farmer": self.farmer.id,
            "crop": self.crop_a.id,
            "village": village.id,
            "latitude": 12.97,
            "longitude": 77.59,
            "farmer_name": self.farmer.name,
            "farmer_phone": self.farmer.phone,
            "land_area": 1.0,
            "problem_category": self.category.id,
            "problem_master": self.problem.id,
            "problem_description": "Test issue",
            "recommendation": "Test advice",
            "observation": "Test observation",
        }

    def test_incomplete_submit_no_db_row(self):
        before = Visit.objects.count()
        r = self.client.post("/api/v1/mobile/visits/", {"farmer": self.farmer.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["message"], SUBMIT_VISIT_REQUIRED_MESSAGE)
        self.assertEqual(Visit.objects.count(), before)

    def test_local_sync_id_idempotent(self):
        body = {**self.payload, "local_sync_id": "offline-uuid-1"}
        r1 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r1.status_code, 200)
        vid = r1.data["data"]["visit_id"]
        r2 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["data"]["duplicate"])
        self.assertEqual(r2.data["data"]["visit_id"], vid)
        self.assertEqual(
            Visit.objects.filter(employee=self.employee, local_sync_id="offline-uuid-1").count(),
            1,
        )

    def test_dashboard_no_active_visit(self):
        r = self.client.get("/api/v1/mobile/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["data"]["active_visit"])
        self.assertEqual(r.data["data"]["pending_visits"], 0)

    def test_visit_detail_and_map(self):
        create = self.client.post("/api/v1/mobile/visits/", self.payload, format="json")
        self.assertEqual(create.status_code, 200, create.data)
        vid = create.data["data"]["visit_id"]
        detail = self.client.get(f"/api/v1/mobile/visits/{vid}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["id"], vid)
        self.assertIn("timeline", detail.data["data"])

        mp = self.client.get("/api/v1/mobile/map/visits/")
        self.assertEqual(mp.status_code, 200)
        self.assertGreaterEqual(len(mp.data["data"]["markers"]), 1)

    def test_farmer_detail_mobile_route(self):
        r = self.client.get(f"/api/v1/mobile/farmers/{self.farmer.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["data"]["id"], self.farmer.id)

    def test_admin_dashboard_unaffected(self):
        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        r = admin_client.get("/api/v1/admin/dashboard/stats/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("visits", r.data["data"])

    def test_local_sync_id_idempotent(self):
        body = {**self.payload, "local_sync_id": "offline-uuid-1"}
        r1 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r1.status_code, 200)
        vid = r1.data["data"]["visit_id"]
        r2 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["data"]["duplicate"])
        self.assertEqual(r2.data["data"]["visit_id"], vid)
        self.assertEqual(
            Visit.objects.filter(employee=self.employee, local_sync_id="offline-uuid-1").count(),
            1,
        )

    def test_dashboard_no_active_visit(self):
        r = self.client.get("/api/v1/mobile/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["data"]["active_visit"])
        self.assertEqual(r.data["data"]["pending_visits"], 0)

    def test_visit_detail_and_map(self):
        create = self.client.post("/api/v1/mobile/visits/", self.payload, format="json")
        self.assertEqual(create.status_code, 200, create.data)
        vid = create.data["data"]["visit_id"]
        detail = self.client.get(f"/api/v1/mobile/visits/{vid}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["id"], vid)
        self.assertIn("timeline", detail.data["data"])

        mp = self.client.get("/api/v1/mobile/map/visits/")
        self.assertEqual(mp.status_code, 200)
        self.assertGreaterEqual(len(mp.data["data"]["markers"]), 1)

    def test_farmer_detail_mobile_route(self):
        r = self.client.get(f"/api/v1/mobile/farmers/{self.farmer.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["data"]["id"], self.farmer.id)

    def test_admin_dashboard_unaffected(self):
        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        r = admin_client.get("/api/v1/admin/dashboard/stats/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("visits", r.data["data"])

    # Tests 12-23: Strict mobile query behavior
    def test_crop_id_category_pest_returns_only_mapped_active_pests(self):
        """Test 12: crop_id + category=pest returns only mapped active Pests."""
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "pest"},
        )
        self.assertEqual(r.status_code, 200)
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        # Should only include mapped active pests for crop_a
        self.assertEqual(master_ids, {self.pest_a1.id, self.pest_a2.id})
        # Should exclude global, legacy FK, other crop, inactive
        self.assertNotIn(self.global_pest.id, master_ids)
        self.assertNotIn(self.legacy_pest.id, master_ids)
        self.assertNotIn(self.other_crop_pest.id, master_ids)
        self.assertNotIn(self.inactive_pest.id, master_ids)

    def test_crop_id_category_disease_returns_only_mapped_active_diseases(self):
        """Test 13: crop_id + category=disease returns only mapped active Diseases."""
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "disease"},
        )
        self.assertEqual(r.status_code, 200)
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        # Should only include mapped active disease for crop_a
        self.assertEqual(master_ids, {self.disease_a.id})

    def test_inactive_pest_excluded(self):
        """Test 14: inactive Pest excluded."""
        # Already covered by test 12, but explicit check
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "pest"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(self.inactive_pest.id, master_ids)

    def test_inactive_disease_excluded(self):
        """Test 15: inactive Disease excluded."""
        inactive_disease = ProblemMaster.objects.create(
            category=self.disease_cat,
            name="Inactive Disease",
            is_active=False,
        )
        CropProblem.objects.create(crop=self.crop_a, problem_master=inactive_disease)
        
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "disease"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(inactive_disease.id, master_ids)

    def test_global_unmapped_pest_excluded(self):
        """Test 16: global unmapped Pest excluded."""
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "pest"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(self.global_pest.id, master_ids)

    def test_global_unmapped_disease_excluded(self):
        """Test 17: global unmapped Disease excluded."""
        global_disease = ProblemMaster.objects.create(
            category=self.disease_cat,
            name="Global Disease",
            is_active=True,
        )
        
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "disease"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(global_disease.id, master_ids)

    def test_legacy_crop_fk_only_row_excluded(self):
        """Test 18: legacy ProblemMaster.crop-only row excluded."""
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "pest"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(self.legacy_pest.id, master_ids)

    def test_other_crop_pest_excluded(self):
        """Test 19: other crop's Pest excluded."""
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "pest"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(self.other_crop_pest.id, master_ids)

    def test_other_crop_disease_excluded(self):
        """Test 20: other crop's Disease excluded."""
        other_disease = ProblemMaster.objects.create(
            category=self.disease_cat,
            name="Other Disease",
            is_active=True,
        )
        CropProblem.objects.create(crop=self.crop_b, problem_master=other_disease)
        
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "disease"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(other_disease.id, master_ids)

    def test_no_cross_crop_leakage(self):
        """Test 21: no cross-crop leakage."""
        # crop_a should not see crop_b's masters
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "pest"},
        )
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(self.other_crop_pest.id, master_ids)
        
        # crop_b should not see crop_a's masters
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_b.id, "category": "pest"},
        )
        master_ids_b = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertNotIn(self.pest_a1.id, master_ids_b)
        self.assertNotIn(self.pest_a2.id, master_ids_b)

    def test_invalid_category_rejected(self):
        """Test 22: invalid category rejected."""
        r = self.client.get(
            "/api/v1/mobile/visit-form-options/",
            {"crop_id": self.crop_a.id, "category": "nutrient_deficiency"},
        )
        self.assertEqual(r.status_code, 200)
        # Should return empty masters for invalid category
        master_ids = {m["id"] for m in r.data["data"]["problem_masters"]}
        self.assertEqual(len(master_ids), 0)

    def test_existing_no_parameter_behavior_remains_backward_compatible(self):
        """Test 23: existing no-parameter behavior remains backward compatible."""
        # Without crop_id and category, should use legacy behavior
        r = self.client.get("/api/v1/mobile/visit-form-options/")
        self.assertEqual(r.status_code, 200)
        # Should return some masters (legacy behavior)
        self.assertGreater(len(r.data["data"]["problem_masters"]), 0)
