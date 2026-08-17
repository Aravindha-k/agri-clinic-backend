"""Phase 1 business locations + multi-problem visit tests."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    CropProblem,
    District,
    Farmer,
    ProblemCategory,
    ProblemMaster,
    Taluk,
    Village,
)
from mobile_api.test_helpers import login_mobile_client
from visits.models import Visit


STRONG = "SecurePass1!"


class BusinessLocationImportTests(TestCase):
    def test_import_creates_expected_hierarchy_and_is_idempotent(self):
        call_command("import_business_locations")
        self.assertEqual(
            District.objects.filter(
                name__in=["Villupuram", "Tiruvannamalai", "Cuddalore"]
            ).count(),
            3,
        )
        self.assertEqual(
            Taluk.objects.filter(
                district__name__in=["Villupuram", "Tiruvannamalai", "Cuddalore"]
            ).count(),
            11,
        )
        self.assertEqual(Village.objects.filter(taluk__isnull=False).count(), 1179)

        mel = Village.objects.filter(
            taluk__name__iexact="Melmalaiyanur",
            taluk__district__name__iexact="Villupuram",
        )
        self.assertEqual(mel.count(), 81)
        sevela = list(mel.filter(name__icontains="SEVELAPURAI"))
        self.assertGreaterEqual(len(sevela), 2)
        codes = {v.official_code for v in sevela}
        self.assertTrue(len(codes) >= 2)

        call_command("import_business_locations")
        self.assertEqual(Village.objects.filter(taluk__isnull=False).count(), 1179)

    def test_taluk_and_village_api_filters(self):
        call_command("import_business_locations")
        user = User.objects.create_user(
            username="loc_emp", password=STRONG, is_staff=True
        )
        client = APIClient()
        client.force_authenticate(user=user)

        districts = client.get("/api/v1/masters/districts/")
        self.assertEqual(districts.status_code, 200)
        villupuram = District.objects.get(name="Villupuram")
        taluks = client.get(f"/api/v1/masters/taluks/?district={villupuram.id}")
        self.assertEqual(taluks.status_code, 200)
        body = taluks.json()
        rows = body.get("data", body)
        if isinstance(rows, dict):
            rows = rows.get("results", rows)
        names = {r["name"] for r in rows}
        self.assertIn("Vanur", names)
        self.assertNotIn("Panruti", names)

        vanur = Taluk.objects.get(name="Vanur", district=villupuram)
        villages = client.get(f"/api/v1/masters/villages/?taluk={vanur.id}")
        self.assertEqual(villages.status_code, 200)
        vbody = villages.json()
        vrows = vbody.get("data", vbody)
        if isinstance(vrows, dict):
            vrows = vrows.get("results", vrows)
        self.assertTrue(vrows)
        self.assertTrue(all("name" in r for r in vrows))
        self.assertTrue(any("official_code" in r for r in vrows))


class FarmerLocationValidationTests(TestCase):
    def setUp(self):
        self.d1 = District.objects.create(name="Villupuram")
        self.d2 = District.objects.create(name="Cuddalore")
        self.t1 = Taluk.objects.create(name="Vanur", district=self.d1)
        self.t2 = Taluk.objects.create(name="Panruti", district=self.d2)
        self.v1 = Village.objects.create(
            name="TestVillage", district=self.d1, taluk=self.t1, official_code="001"
        )
        EmployeeProfile.objects.create(
            user=User.objects.create_user(username="farm_emp", password=STRONG),
            employee_id="F-LOC-1",
            phone="9000000002",
            is_active_employee=True,
            can_login=True,
        )
        self.client = login_mobile_client(employee_id="F-LOC-1", password=STRONG)

    def test_rejects_cross_district_taluk(self):
        resp = self.client.post(
            "/api/v1/farmers/",
            {
                "name": "Bad Loc",
                "phone": "9888888801",
                "district": self.d1.id,
                "taluk": self.t2.id,
                "village": self.v1.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accepts_valid_hierarchy(self):
        resp = self.client.post(
            "/api/v1/farmers/",
            {
                "name": "Good Loc",
                "phone": "9888888802",
                "district": self.d1.id,
                "taluk": self.t1.id,
                "village": self.v1.id,
            },
            format="json",
        )
        self.assertIn(resp.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED))

    def test_new_farmer_requires_taluk(self):
        resp = self.client.post(
            "/api/v1/farmers/",
            {
                "name": "Missing Taluk",
                "phone": "9888888803",
                "district": self.d1.id,
                "village": self.v1.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_legacy_null_taluk_list_detail_and_unrelated_patch(self):
        emp = User.objects.get(username="farm_emp")
        legacy_village = Village.objects.create(
            name="KolathurLegacy", district=self.d1, taluk=None
        )
        farmer = Farmer.objects.create(
            name="Legacy Null Taluk",
            phone="9888888804",
            district=self.d1,
            village=legacy_village,
            assigned_employee=emp,
        )

        list_resp = self.client.get("/api/v1/farmers/?page_size=50")
        self.assertEqual(list_resp.status_code, 200)
        body = list_resp.json()
        data = body.get("data", body)
        results = data.get("results", data) if isinstance(data, dict) else data
        row = next(r for r in results if r["id"] == farmer.id)
        self.assertIn("taluk_name", row)
        self.assertIn(row["taluk_name"], ("", None))

        detail = self.client.get(f"/api/v1/farmers/{farmer.id}/")
        self.assertEqual(detail.status_code, 200)
        detail_body = detail.json()
        detail_data = detail_body.get("data", detail_body)
        self.assertIn(detail_data.get("taluk_name"), ("", None))

        patch = self.client.patch(
            f"/api/v1/farmers/{farmer.id}/",
            {"address": "Keep taluk null"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200)
        farmer.refresh_from_db()
        self.assertIsNone(farmer.taluk_id)
        self.assertEqual(farmer.village_id, legacy_village.id)
        self.assertEqual(farmer.address, "Keep taluk null")

        incomplete = self.client.patch(
            f"/api/v1/farmers/{farmer.id}/",
            {"village": self.v1.id},
            format="json",
        )
        self.assertEqual(incomplete.status_code, status.HTTP_400_BAD_REQUEST)
        farmer.refresh_from_db()
        self.assertEqual(farmer.village_id, legacy_village.id)
        self.assertIsNone(farmer.taluk_id)

        complete = self.client.patch(
            f"/api/v1/farmers/{farmer.id}/",
            {
                "district": self.d1.id,
                "taluk": self.t1.id,
                "village": self.v1.id,
            },
            format="json",
        )
        self.assertEqual(complete.status_code, 200)
        farmer.refresh_from_db()
        self.assertEqual(farmer.taluk_id, self.t1.id)
        self.assertEqual(farmer.village_id, self.v1.id)


class CropPestImportAndVisitMultiProblemTests(TestCase):
    def setUp(self):
        EmployeeProfile.objects.create(
            user=User.objects.create_user(username="visit_emp", password=STRONG),
            employee_id="V-MP-1",
            phone="9000000003",
            is_active_employee=True,
            can_login=True,
        )
        self.district = District.objects.create(name="Villupuram")
        self.taluk = Taluk.objects.create(name="Vanur", district=self.district)
        self.village = Village.objects.create(
            name="Pattanur", district=self.district, taluk=self.taluk
        )
        self.paddy = Crop.objects.create(name_en="Paddy", name_ta="நெல்")
        self.tomato = Crop.objects.create(name_en="Tomato", name_ta="தக்காளி")
        call_command("import_crop_pests")
        self.client = login_mobile_client(employee_id="V-MP-1", password=STRONG)

    def _base_payload(self, **extra):
        pest_cat = ProblemCategory.objects.get(code=ProblemCategory.CODE_PEST)
        data = {
            "farmer_name": "Test Farmer",
            "phone_number": "9876543210",
            "village_id": self.village.id,
            "crop_id": self.paddy.id,
            "acreage": 1.5,
            "problem_category_id": pest_cat.id,
            "problem_description": "Field observation",
            "latitude": 12.0,
            "longitude": 79.5,
            "create_farmer_if_missing": True,
        }
        data.update(extra)
        return data

    def test_pest_import_and_sathupatrakurai(self):
        self.assertTrue(
            ProblemMaster.objects.filter(
                name__iexact="Yellow Stem Borer", category__code="pest"
            ).exists()
        )
        ysb = ProblemMaster.objects.filter(name__iexact="Yellow Stem Borer").first()
        self.assertTrue(ysb.tamil_name)
        self.assertTrue(
            CropProblem.objects.filter(problem_master=ysb, crop=self.paddy).exists()
        )
        sathu = ProblemMaster.objects.get(name="Sathupatrakurai")
        self.assertEqual(sathu.category.code, ProblemCategory.CODE_NUTRIENT)
        self.assertEqual(sathu.tamil_name, "சத்துப்பற்றாக்குறை")
        self.assertFalse(CropProblem.objects.filter(problem_master=sathu).exists())

    def test_legacy_single_problem_still_works(self):
        ysb = ProblemMaster.objects.filter(
            name__iexact="Yellow Stem Borer", category__code="pest"
        ).first()
        resp = self.client.post(
            "/api/v1/mobile/visits/",
            self._base_payload(problem_master_id=ysb.id),
            format="json",
        )
        self.assertEqual(resp.status_code, 200, getattr(resp, "data", resp.content))
        visit = Visit.objects.latest("id")
        self.assertEqual(visit.problem_master_id, ysb.id)
        self.assertEqual(list(visit.problem_items.values_list("id", flat=True)), [ysb.id])

    def test_multi_problem_and_wrong_crop(self):
        ysb = ProblemMaster.objects.filter(name__iexact="Yellow Stem Borer").first()
        leaf = ProblemMaster.objects.filter(name__iexact="Leaf Folder").first()
        resp_ok = self.client.post(
            "/api/v1/mobile/visits/",
            self._base_payload(problem_item_ids=[ysb.id, leaf.id]),
            format="json",
        )
        self.assertEqual(
            resp_ok.status_code, 200, getattr(resp_ok, "data", resp_ok.content)
        )
        visit = Visit.objects.latest("id")
        self.assertEqual(
            set(visit.problem_items.values_list("id", flat=True)), {ysb.id, leaf.id}
        )

        resp_bad = self.client.post(
            "/api/v1/mobile/visits/",
            self._base_payload(crop_id=self.tomato.id, problem_item_ids=[ysb.id]),
            format="json",
        )
        self.assertEqual(resp_bad.status_code, 400)

    def test_duplicate_ids_deduped(self):
        ysb = ProblemMaster.objects.filter(name__iexact="Yellow Stem Borer").first()
        resp = self.client.post(
            "/api/v1/mobile/visits/",
            self._base_payload(problem_item_ids=[ysb.id, ysb.id]),
            format="json",
        )
        self.assertEqual(resp.status_code, 200, getattr(resp, "data", resp.content))
        visit = Visit.objects.latest("id")
        self.assertEqual(visit.problem_items.count(), 1)


class FarmerListPerformanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="list_emp", password=STRONG, is_staff=True
        )
        EmployeeProfile.objects.create(
            user=self.user,
            employee_id="L-1",
            phone="9000000004",
            is_active_employee=True,
            can_login=True,
        )
        d = District.objects.create(name="PerfDistrict")
        t = Taluk.objects.create(name="PerfTaluk", district=d)
        v = Village.objects.create(name="PerfVillage", district=d, taluk=t)
        v_null = Village.objects.create(name="PerfLegacyVillage", district=d, taluk=None)
        for i in range(25):
            Farmer.objects.create(
                name=f"Farmer {i}",
                phone=f"98000000{i:02d}",
                district=d,
                taluk=t,
                village=v,
            )
        self.legacy = Farmer.objects.create(
            name="Legacy Null Taluk",
            phone="9800000099",
            district=d,
            village=v_null,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_farmer_list_paginated(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get("/api/v1/farmers/?page_size=20")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        data = body.get("data", body)
        results = data.get("results", data)
        self.assertLessEqual(len(results), 20)
        self.assertLess(len(ctx), 25)
        self.assertIn("taluk_name", results[0])

    def test_legacy_null_taluk_visible_in_list(self):
        resp = self.client.get("/api/v1/farmers/?search=Legacy%20Null%20Taluk")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        data = body.get("data", body)
        results = data.get("results", data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.legacy.id)
        self.assertIn(results[0]["taluk_name"], ("", None))
