"""Village-only operational master: CRUD, uniqueness, and Excel import."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APIClient

from masters.models import Village

STRONG = "SecurePass1!"


class OperationalVillageMasterTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="village_admin", password=STRONG, is_staff=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_admin_creates_village_without_district_taluk(self):
        resp = self.client.post(
            "/api/v1/masters/villages/",
            {
                "name": "Kedar",
                "name_ta": "கேடார்",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        village = Village.objects.get(name="Kedar")
        self.assertEqual(village.name_ta, "கேடார்")
        self.assertIsNone(village.district_id)
        self.assertIsNone(village.taluk_id)
        body = resp.json()
        data = body.get("data", body)
        self.assertEqual(data.get("name_ta"), "கேடார்")

    def test_duplicate_village_name_normalized(self):
        Village.objects.create(name="Kedar", name_ta="கேடார்")
        for name in ("kedar", " Kedar", "KEDAR"):
            resp = self.client.post(
                "/api/v1/masters/villages/",
                {"name": name, "tamil_name": "கேடார்", "is_active": True},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, name)
        self.assertEqual(Village.objects.filter(name__iexact="kedar").count(), 1)

    def test_prefix_search_english_and_tamil(self):
        Village.objects.create(name="Kedar", name_ta="கேடார்")
        Village.objects.create(name="Ananthapuram", name_ta="ஆனந்தபுரம்")
        ked = self.client.get("/api/v1/masters/villages/", {"search": "Ked"})
        ked_body = ked.json()
        ked_data = ked_body.get("data", ked_body)
        ked_rows = ked_data.get("results", ked_data)
        self.assertIn("Kedar", {row["name"] for row in ked_rows})
        miss = self.client.get("/api/v1/masters/villages/", {"search": "edar"})
        miss_body = miss.json()
        miss_data = miss_body.get("data", miss_body)
        miss_rows = miss_data.get("results", miss_data)
        self.assertNotIn("Kedar", {row["name"] for row in miss_rows})
        tamil = self.client.get("/api/v1/masters/villages/", {"search": "கேட"})
        tamil_body = tamil.json()
        tamil_data = tamil_body.get("data", tamil_body)
        tamil_rows = tamil_data.get("results", tamil_data)
        self.assertIn("Kedar", {row["name"] for row in tamil_rows})
        tamil_miss = self.client.get("/api/v1/masters/villages/", {"search": "டார்"})
        tamil_miss_body = tamil_miss.json()
        tamil_miss_data = tamil_miss_body.get("data", tamil_miss_body)
        tamil_miss_rows = tamil_miss_data.get("results", tamil_miss_data)
        self.assertNotIn("Kedar", {row["name"] for row in tamil_miss_rows})

    def test_name_ta_persists_and_updates(self):
        create = self.client.post(
            "/api/v1/masters/villages/",
            {"name": "Kedar Persist", "name_ta": "கேடார்"},
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.data)
        body = create.json()
        data = body.get("data", body)
        village_id = data["id"]
        get1 = self.client.get(f"/api/v1/masters/villages/{village_id}/")
        got = get1.json().get("data", get1.json())
        self.assertEqual(got["name_ta"], "கேடார்")
        patch = self.client.patch(
            f"/api/v1/masters/villages/{village_id}/",
            {"name_ta": "கேதார் புதியது"},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.data)
        get2 = self.client.get(f"/api/v1/masters/villages/{village_id}/")
        updated = get2.json().get("data", get2.json())
        self.assertEqual(updated["name_ta"], "கேதார் புதியது")
        village = Village.objects.get(pk=village_id)
        self.assertEqual(village.name_ta, "கேதார் புதியது")


class OperationalVillageImportTests(TestCase):
    def _write_workbook(self, directory: str) -> Path:
        path = Path(directory) / "villages.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.append(
            ["S NO", "Field staff", "Village", "village tamil name", "Firka", "Taluk", "District"]
        )
        sheet.append([1, "Ravi", "Kedar", "கேடார்", "Firka X", "Vanur", "Villupuram"])
        sheet.append([2, "Ravi", " kedar ", "ignored-dupe", "Firka Y", "Vanur", "Villupuram"])
        sheet.append([3, "Kavya", "Ananthapuram", "ஆனந்தபுரம்", "Firka Z", "Tindivanam", "Villupuram"])
        book.save(path)
        book.close()
        return path

    def test_import_uses_village_and_tamil_only_and_dedupes(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(tmp)
            call_command("import_operational_villages", str(path), "--execute")
        names = set(Village.objects.values_list("name", flat=True))
        self.assertEqual(names, {"Kedar", "Ananthapuram"})
        kedar = Village.objects.get(name="Kedar")
        self.assertEqual(kedar.name_ta, "கேடார்")
        self.assertIsNone(kedar.district_id)
        self.assertIsNone(kedar.taluk_id)
        self.assertEqual(kedar.firka_name, "")
        self.assertEqual(
            Village.objects.get(name="Ananthapuram").name_ta,
            "ஆனந்தபுரம்",
        )

    def test_import_defaults_to_dry_run(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(tmp)
            call_command("import_operational_villages", str(path))
        self.assertEqual(Village.objects.count(), 0)
