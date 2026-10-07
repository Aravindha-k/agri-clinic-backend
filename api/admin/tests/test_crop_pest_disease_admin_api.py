"""Admin Crop → Pest/Disease mapping API tests (CropProblem source of truth)."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    CropProblem,
    District,
    Farmer,
    FarmerField,
    ProblemCategory,
    ProblemMaster,
    Taluk,
    Village,
)
from masters.problem_item_utils import problem_categories_with_active_items
from visits.models import Visit


STRONG_PASSWORD = "SecurePass1!"

LIST_URL = "/api/v1/admin/crop-pest-disease/"


def _auth(user: User) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def _staff_admin():
    user = User.objects.create_user(
        username="cpd.admin",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="CPD-ADM",
        phone="9111222001",
        is_active_employee=True,
        can_login=True,
        role="admin",
    )
    return user


def _field_employee():
    user = User.objects.create_user(
        username="cpd.field",
        password=STRONG_PASSWORD,
        is_staff=False,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="CPD-FLD",
        phone="9111222002",
        is_active_employee=True,
        can_login=True,
    )
    return user


class CropPestDiseaseAdminAPITests(TestCase):
    def setUp(self):
        self.admin = _staff_admin()
        self.employee = _field_employee()
        self.admin_client = _auth(self.admin)
        self.emp_client = _auth(self.employee)

        self.pest_cat = ProblemCategory.objects.create(
            code=ProblemCategory.CODE_PEST,
            name="Pest",
            is_active=True,
        )
        self.disease_cat = ProblemCategory.objects.create(
            code=ProblemCategory.CODE_DISEASE,
            name="Disease",
            is_active=False,  # intentional field/mobile freeze
        )
        self.nutrient_cat = ProblemCategory.objects.create(
            code=ProblemCategory.CODE_NUTRIENT,
            name="Nutrient Deficiency",
            is_active=True,
        )

        self.crop_a = Crop.objects.create(
            name_en="Tomato", name_ta="தக்காளி", is_active=True
        )
        self.crop_b = Crop.objects.create(
            name_en="Paddy", name_ta="நெல்", is_active=True
        )

        self.pest_a1 = ProblemMaster.objects.create(
            category=self.pest_cat, name="Fruit Borer", tamil_name="FB", is_active=True
        )
        self.pest_a2 = ProblemMaster.objects.create(
            category=self.pest_cat, name="Aphid", tamil_name="", is_active=True
        )
        self.pest_b = ProblemMaster.objects.create(
            category=self.pest_cat, name="Stem Borer", tamil_name="", is_active=True
        )
        self.disease_a = ProblemMaster.objects.create(
            category=self.disease_cat,
            name="Bacterial Wilt",
            tamil_name="",
            is_active=True,
        )
        self.disease_b = ProblemMaster.objects.create(
            category=self.disease_cat,
            name="Blast",
            tamil_name="",
            is_active=True,
        )
        self.unmapped_pest = ProblemMaster.objects.create(
            category=self.pest_cat, name="Thrips", tamil_name="", is_active=True
        )

        # PM142 legacy anomaly under pest
        self.pm142 = ProblemMaster(
            id=142,
            category=self.pest_cat,
            name="Nutrient Deficiency",
            tamil_name="",
            is_active=True,
            crop=None,
        )
        self.pm142.save()

        CropProblem.objects.create(crop=self.crop_a, problem_master=self.pest_a1)
        CropProblem.objects.create(crop=self.crop_a, problem_master=self.pest_a2)
        CropProblem.objects.create(crop=self.crop_a, problem_master=self.disease_a)
        CropProblem.objects.create(crop=self.crop_b, problem_master=self.pest_b)
        CropProblem.objects.create(crop=self.crop_b, problem_master=self.disease_b)

        # Historical visit referencing PM142 + crop_a pest mapping
        district = District.objects.create(name="CPD Dist")
        taluk = Taluk.objects.create(name="CPD Taluk", district=district)
        village = Village.objects.create(
            name="CPD Village", district=district, taluk=taluk
        )
        farmer = Farmer.objects.create(
            name="CPD Farmer",
            phone="9111222999",
            district=district,
            village=village,
            assigned_employee=self.employee,
        )
        field = FarmerField.objects.create(
            farmer=farmer,
            land_name="CPD Field",
            land_size="1.00",
            created_by_employee=self.employee,
        )
        self.visit = Visit.objects.create(
            farmer=farmer,
            field=field,
            crop=self.crop_a,
            employee=self.employee,
            problem_category=self.pest_cat,
            problem_master=self.pm142,
            notes="historical",
        )
        self.visit.problem_items.set([self.pest_a1])
        self.visit_pm_id = self.visit.problem_master_id
        self.visit_item_ids = set(self.visit.problem_items.values_list("id", flat=True))

    def test_a_b_c_crop_list_counts_from_cropproblem_including_inactive_disease(self):
        r = self.admin_client.get(LIST_URL)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["success"])
        by_id = {row["id"]: row for row in r.data["data"]["results"]}
        self.assertEqual(by_id[self.crop_a.id]["pest_count"], 2)
        self.assertEqual(by_id[self.crop_a.id]["disease_count"], 1)
        self.assertEqual(by_id[self.crop_a.id]["name"], "Tomato")
        self.assertEqual(by_id[self.crop_a.id]["tamil_name"], "தக்காளி")
        self.assertTrue(by_id[self.crop_a.id]["is_active"])
        self.assertEqual(by_id[self.crop_b.id]["pest_count"], 1)
        self.assertEqual(by_id[self.crop_b.id]["disease_count"], 1)
        # Disease category still inactive
        self.disease_cat.refresh_from_db()
        self.assertFalse(self.disease_cat.is_active)

    def test_b_counts_ignore_legacy_problem_master_crop_fk(self):
        # Legacy FK alone must not inflate counts
        orphan = ProblemMaster.objects.create(
            category=self.pest_cat,
            name="Legacy Only FK",
            crop=self.crop_a,
            is_active=True,
        )
        r = self.admin_client.get(LIST_URL)
        by_id = {row["id"]: row for row in r.data["data"]["results"]}
        self.assertEqual(by_id[self.crop_a.id]["pest_count"], 2)
        self.assertFalse(
            CropProblem.objects.filter(
                crop=self.crop_a, problem_master=orphan
            ).exists()
        )

    def test_d_e_n_detail_separates_and_isolates_crops(self):
        r = self.admin_client.get(f"{LIST_URL}{self.crop_a.id}/")
        self.assertEqual(r.status_code, 200, r.data)
        data = r.data["data"]
        pest_ids = {p["id"] for p in data["pests"]}
        disease_ids = {d["id"] for d in data["diseases"]}
        self.assertEqual(pest_ids, {self.pest_a1.id, self.pest_a2.id})
        self.assertEqual(disease_ids, {self.disease_a.id})
        self.assertNotIn(self.pest_b.id, pest_ids)
        self.assertNotIn(self.disease_b.id, disease_ids)
        self.assertEqual(data["pest_count"], 2)
        self.assertEqual(data["disease_count"], 1)
        # Stable integer IDs
        self.assertIsInstance(data["pests"][0]["id"], int)
        self.assertIsInstance(data["diseases"][0]["id"], int)

        r_b = self.admin_client.get(f"{LIST_URL}{self.crop_b.id}/")
        pest_b = {p["id"] for p in r_b.data["data"]["pests"]}
        self.assertEqual(pest_b, {self.pest_b.id})
        self.assertNotIn(self.pest_a1.id, pest_b)

    def test_f_pm142_excluded_from_available_and_map_rejected(self):
        r = self.admin_client.get(
            f"{LIST_URL}{self.crop_a.id}/available-masters/",
            {"category": "pest", "search": "Nutrient", "include_mapped": "true"},
        )
        self.assertEqual(r.status_code, 200, r.data)
        ids = {row["id"] for row in r.data["data"]["results"]}
        self.assertNotIn(142, ids)

        r_map = self.admin_client.post(
            f"{LIST_URL}{self.crop_a.id}/map/",
            {"problem_master_id": 142},
            format="json",
        )
        self.assertEqual(r_map.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            CropProblem.objects.filter(
                crop=self.crop_a, problem_master_id=142
            ).exists()
        )

    def test_g_h_map_idempotent(self):
        r = self.admin_client.post(
            f"{LIST_URL}{self.crop_a.id}/map/",
            {"problem_master_id": self.unmapped_pest.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertTrue(r.data["data"]["created"])
        self.assertTrue(
            CropProblem.objects.filter(
                crop=self.crop_a, problem_master=self.unmapped_pest
            ).exists()
        )
        # ProblemMaster.crop unchanged
        self.unmapped_pest.refresh_from_db()
        self.assertIsNone(self.unmapped_pest.crop_id)

        r2 = self.admin_client.post(
            f"{LIST_URL}{self.crop_a.id}/map/",
            {"problem_master_id": self.unmapped_pest.id},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)
        self.assertFalse(r2.data["data"]["created"])
        self.assertTrue(r2.data["data"]["already_mapped"])
        self.assertEqual(
            CropProblem.objects.filter(
                crop=self.crop_a, problem_master=self.unmapped_pest
            ).count(),
            1,
        )

    def test_i_j_k_unmap_deletes_cropproblem_only_visits_intact(self):
        link = CropProblem.objects.get(
            crop=self.crop_a, problem_master=self.pest_a1
        )
        r = self.admin_client.post(
            f"{LIST_URL}{self.crop_a.id}/unmap/",
            {"problem_master_id": self.pest_a1.id},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["data"]["unmapped"])
        self.assertFalse(CropProblem.objects.filter(pk=link.pk).exists())
        self.assertTrue(ProblemMaster.objects.filter(pk=self.pest_a1.id).exists())

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.problem_master_id, self.visit_pm_id)
        self.assertEqual(
            set(self.visit.problem_items.values_list("id", flat=True)),
            self.visit_item_ids,
        )
        # Unmap must not touch crop B
        self.assertTrue(
            CropProblem.objects.filter(
                crop=self.crop_b, problem_master=self.pest_b
            ).exists()
        )

    def test_l_disease_remains_inactive(self):
        self.admin_client.get(LIST_URL)
        self.admin_client.get(f"{LIST_URL}{self.crop_a.id}/")
        self.admin_client.post(
            f"{LIST_URL}{self.crop_a.id}/map/",
            {"problem_master_id": self.disease_b.id},
            format="json",
        )
        self.disease_cat.refresh_from_db()
        self.assertFalse(self.disease_cat.is_active)

    def test_m_field_mobile_categories_still_hide_inactive_disease(self):
        cats = list(problem_categories_with_active_items())
        codes = {c.code for c in cats}
        self.assertNotIn(ProblemCategory.CODE_DISEASE, codes)
        self.assertIn(ProblemCategory.CODE_PEST, codes)

        # Field dropdown endpoint must not list disease category
        r = self.emp_client.get("/api/v1/masters/visit-form-options/")
        self.assertEqual(r.status_code, 200, r.data)
        form_codes = {
            c["code"] for c in r.data["data"]["problem_categories"]
        }
        self.assertNotIn(ProblemCategory.CODE_DISEASE, form_codes)

    def test_o_field_employee_cannot_mutate(self):
        r_list = self.emp_client.get(LIST_URL)
        self.assertIn(r_list.status_code, (401, 403))

        r_map = self.emp_client.post(
            f"{LIST_URL}{self.crop_a.id}/map/",
            {"problem_master_id": self.unmapped_pest.id},
            format="json",
        )
        self.assertIn(r_map.status_code, (401, 403))
        self.assertFalse(
            CropProblem.objects.filter(
                crop=self.crop_a, problem_master=self.unmapped_pest
            ).exists()
        )

        r_unmap = self.emp_client.post(
            f"{LIST_URL}{self.crop_a.id}/unmap/",
            {"problem_master_id": self.pest_a1.id},
            format="json",
        )
        self.assertIn(r_unmap.status_code, (401, 403))
        self.assertTrue(
            CropProblem.objects.filter(
                crop=self.crop_a, problem_master=self.pest_a1
            ).exists()
        )

    def test_available_masters_marks_mapped_and_search(self):
        r = self.admin_client.get(
            f"{LIST_URL}{self.crop_a.id}/available-masters/",
            {"category": "pest", "search": "Thrips"},
        )
        self.assertEqual(r.status_code, 200, r.data)
        rows = r.data["data"]["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.unmapped_pest.id)
        self.assertFalse(rows[0]["already_mapped"])

        r2 = self.admin_client.get(
            f"{LIST_URL}{self.crop_a.id}/available-masters/",
            {"category": "disease", "include_mapped": "true"},
        )
        self.assertEqual(r2.status_code, 200, r2.data)
        ids = {row["id"]: row for row in r2.data["data"]["results"]}
        self.assertIn(self.disease_a.id, ids)
        self.assertTrue(ids[self.disease_a.id]["already_mapped"])
        self.assertIn(self.disease_b.id, ids)

    def test_p_list_query_count_no_n_plus_one(self):
        # Extra crops + mappings should not scale queries linearly with crop count
        for i in range(8):
            c = Crop.objects.create(name_en=f"Extra{i}", name_ta=f"E{i}", is_active=True)
            pm = ProblemMaster.objects.create(
                category=self.pest_cat, name=f"ExtraPest{i}", is_active=True
            )
            CropProblem.objects.create(crop=c, problem_master=pm)

        with CaptureQueriesContext(connection) as ctx1:
            r1 = self.admin_client.get(LIST_URL)
        self.assertEqual(r1.status_code, 200)

        for i in range(8, 16):
            c = Crop.objects.create(name_en=f"Extra{i}", name_ta=f"E{i}", is_active=True)
            pm = ProblemMaster.objects.create(
                category=self.pest_cat, name=f"ExtraPest{i}", is_active=True
            )
            CropProblem.objects.create(crop=c, problem_master=pm)

        with CaptureQueriesContext(connection) as ctx2:
            r2 = self.admin_client.get(LIST_URL)
        self.assertEqual(r2.status_code, 200)
        # Allow small auth/session variance; must not grow ~1 query per crop
        self.assertLessEqual(len(ctx2), len(ctx1) + 3)
        self.assertLess(len(ctx2), 25)

    def test_map_rejects_non_pest_disease(self):
        nutrient = ProblemMaster.objects.create(
            category=self.nutrient_cat, name="Zn Def", is_active=True
        )
        r = self.admin_client.post(
            f"{LIST_URL}{self.crop_a.id}/map/",
            {"problem_master_id": nutrient.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_problem_master_create_disease_does_not_activate_category(self):
        r = self.admin_client.post(
            "/api/v1/admin/problem-masters/",
            {
                "category": self.disease_cat.id,
                "name": "New Disease X",
                "tamil_name": "",
                "is_active": True,
            },
            format="json",
        )
        self.assertIn(r.status_code, (200, 201), r.data)
        self.disease_cat.refresh_from_db()
        self.assertFalse(self.disease_cat.is_active)
        self.assertTrue(
            ProblemMaster.objects.filter(
                name="New Disease X", category=self.disease_cat
            ).exists()
        )
