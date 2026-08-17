"""Location master read-contract and village classification tests."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from masters.location_audit import (
    CLASS_ACCEPTED_LEGACY_UNRESOLVED,
    CLASS_INACTIVE_IMPORT_TWIN,
    CLASS_LEGACY_LINKED,
    CLASS_LEGACY_UNLINKED,
    CLASS_OFFICIAL_IMPORTED,
    CLASS_OTHER,
    classify_village,
    reconcile_village_counts,
)
from masters.models import District, Farmer, Taluk, Village

STRONG = "SecurePass1!"


class LocationMasterReadApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="loc_admin", password=STRONG, is_staff=True
        )
        self.employee = User.objects.create_user(
            username="loc_emp", password=STRONG, is_staff=False
        )
        self.d1 = District.objects.create(name="Villupuram")
        self.d2 = District.objects.create(name="Cuddalore")
        self.t1 = Taluk.objects.create(name="Vanur", district=self.d1)
        self.t2 = Taluk.objects.create(name="Panruti", district=self.d2)
        self.v_official = Village.objects.create(
            name="Pattanur",
            district=self.d1,
            taluk=self.t1,
            official_code="001",
            official_source="https://example.test/pattanur",
        )
        self.v_sevela_a = Village.objects.create(
            name="SEVELAPURAI",
            district=self.d1,
            taluk=self.t1,
            official_code="010",
        )
        self.v_sevela_b = Village.objects.create(
            name="SEVELAPURAI",
            district=self.d1,
            taluk=self.t1,
            official_code="011",
        )
        self.v_legacy = Village.objects.create(
            name="Kolathur",
            district=self.d1,
            taluk=None,
        )
        self.v_inactive = Village.objects.create(
            name="OldTwin",
            district=self.d1,
            taluk=self.t1,
            official_code="",
            is_active=False,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)

    def _rows(self, response):
        body = response.json()
        data = body.get("data", body)
        if isinstance(data, dict) and "results" in data:
            return data["results"], data.get("count")
        if isinstance(body, dict) and "results" in body:
            return body["results"], body.get("count")
        return data, None

    def test_taluk_list_filter_and_village_count(self):
        resp = self.client.get(f"/api/v1/masters/taluks/?district={self.d1.id}")
        self.assertEqual(resp.status_code, 200)
        rows, _ = self._rows(resp)
        names = {r["name"] for r in rows}
        self.assertIn("Vanur", names)
        self.assertNotIn("Panruti", names)
        vanur = next(r for r in rows if r["name"] == "Vanur")
        self.assertEqual(vanur["district"], self.d1.id)
        self.assertEqual(vanur["district_name"], "Villupuram")
        self.assertTrue(vanur["is_active"])
        self.assertEqual(vanur["village_count"], 3)

    def test_taluk_village_count_excludes_inactive(self):
        resp = self.client.get(f"/api/v1/masters/taluks/?district={self.d1.id}")
        rows, _ = self._rows(resp)
        vanur = next(r for r in rows if r["name"] == "Vanur")
        self.assertEqual(vanur["village_count"], 3)

    def test_district_counts_are_active(self):
        resp = self.client.get("/api/v1/masters/districts/")
        self.assertEqual(resp.status_code, 200)
        rows, _ = self._rows(resp)
        villupuram = next(r for r in rows if r["name"] == "Villupuram")
        self.assertEqual(villupuram["taluk_count"], 1)
        self.assertEqual(villupuram["village_count"], 4)

    def test_location_summary_uses_active_basis(self):
        resp = self.client.get("/api/v1/masters/location-summary/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["count_basis"], "active")
        self.assertEqual(data["districts"]["active"], 2)
        self.assertEqual(data["taluks"]["active"], 2)
        self.assertEqual(data["villages"]["active"], 4)
        self.assertEqual(data["villages"]["total"], 5)

    def test_inactive_villages_hidden_unless_show_inactive(self):
        hidden = self.client.get("/api/v1/masters/villages/?page_size=500")
        self.assertEqual(hidden.status_code, 200)
        rows, count = self._rows(hidden)
        ids = {r["id"] for r in rows}
        self.assertNotIn(self.v_inactive.id, ids)
        self.assertIsNotNone(count)
        self.assertEqual(count, 4)

        shown = self.client.get(
            "/api/v1/masters/villages/?show_inactive=true&page_size=500"
        )
        rows_all, count_all = self._rows(shown)
        ids_all = {r["id"] for r in rows_all}
        self.assertIn(self.v_inactive.id, ids_all)
        self.assertEqual(count_all, 5)

    def test_legacy_taluk_null_village_remains_readable(self):
        resp = self.client.get("/api/v1/masters/villages/?page_size=500")
        rows, _ = self._rows(resp)
        ids = {r["id"] for r in rows}
        self.assertIn(self.v_legacy.id, ids)
        legacy = next(r for r in rows if r["id"] == self.v_legacy.id)
        self.assertIsNone(legacy["taluk"])

    def test_same_name_different_code_both_valid(self):
        resp = self.client.get(
            f"/api/v1/masters/villages/?taluk={self.t1.id}&page_size=500"
        )
        self.assertEqual(resp.status_code, 200)
        rows, _ = self._rows(resp)
        sevela = [r for r in rows if r["name"] == "SEVELAPURAI"]
        codes = {r["official_code"] for r in sevela}
        self.assertEqual(codes, {"010", "011"})
        self.assertEqual(len(sevela), 2)

    def test_employee_can_read_taluks(self):
        emp = APIClient()
        emp.force_authenticate(user=self.employee)
        resp = emp.get("/api/v1/masters/taluks/")
        self.assertEqual(resp.status_code, 200)


class VillageClassificationTests(TestCase):
    def test_classes_are_exclusive_and_reconcile(self):
        d = District.objects.create(name="Villupuram")
        t = Taluk.objects.create(name="Kandachipuram", district=d)
        official = Village.objects.create(
            name="Othiyathur",
            district=d,
            taluk=t,
            official_code="142",
            official_source="https://example.test/o",
        )
        twin = Village.objects.create(
            name="OTHIYATHUR",
            district=d,
            taluk=t,
            official_code="",
            is_active=False,
        )
        accepted = Village.objects.create(name="Kolathur", district=d, taluk=None)
        unlinked = Village.objects.create(
            name="Aalathur", district=d, taluk=None, is_active=False
        )
        linked = Village.objects.create(name="Ulagalampoondi", district=d, taluk=None)
        other = Village.objects.create(
            name="KrishnapuramExtra",
            district=d,
            taluk=t,
            official_code="",
            official_source="",
        )
        Farmer.objects.create(name="F1", phone="9000000001", village=linked, district=d)

        self.assertEqual(
            classify_village(official, farmer_count=0, twin_ids={twin.id}),
            CLASS_OFFICIAL_IMPORTED,
        )
        self.assertEqual(
            classify_village(twin, farmer_count=0, twin_ids={twin.id}),
            CLASS_INACTIVE_IMPORT_TWIN,
        )
        self.assertEqual(
            classify_village(accepted, farmer_count=1, twin_ids={twin.id}),
            CLASS_ACCEPTED_LEGACY_UNRESOLVED,
        )
        self.assertEqual(
            classify_village(unlinked, farmer_count=0, twin_ids={twin.id}),
            CLASS_LEGACY_UNLINKED,
        )
        self.assertEqual(
            classify_village(linked, farmer_count=1, twin_ids={twin.id}),
            CLASS_LEGACY_LINKED,
        )
        self.assertEqual(
            classify_village(other, farmer_count=0, twin_ids={twin.id}),
            CLASS_OTHER,
        )

        report = reconcile_village_counts()
        self.assertTrue(report["reconciles"])
        self.assertEqual(report["total"], 6)
        self.assertEqual(report["classes"][CLASS_OFFICIAL_IMPORTED], 1)
        self.assertEqual(report["classes"][CLASS_INACTIVE_IMPORT_TWIN], 1)
        self.assertEqual(report["classes"][CLASS_ACCEPTED_LEGACY_UNRESOLVED], 1)
        self.assertEqual(report["classes"][CLASS_LEGACY_UNLINKED], 1)
        self.assertEqual(report["classes"][CLASS_LEGACY_LINKED], 1)
        self.assertEqual(report["classes"][CLASS_OTHER], 1)
