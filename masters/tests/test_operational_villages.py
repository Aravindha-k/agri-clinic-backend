"""Village-only operational master: CRUD, uniqueness, and Excel import."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
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
    def setUp(self):
        self.sasi = User.objects.create_user(
            username="sasi_user", password=STRONG, first_name="Sasikumar"
        )
        self.sasi_profile = EmployeeProfile.objects.create(
            user=self.sasi,
            employee_id="KAC-0004",
            phone="9000000001",
            role="FieldAgent",
        )
        self.kavi = User.objects.create_user(
            username="kavi_user", password=STRONG, first_name="Kaviyarasan"
        )
        self.kavi_profile = EmployeeProfile.objects.create(
            user=self.kavi,
            employee_id="KAC-0003",
            phone="9000000002",
            role="FieldAgent",
        )

    def _write_workbook(self, directory: str, rows: list[list]) -> Path:
        path = Path(directory) / "villages.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.append(
            [
                "S NO",
                "Field staff",
                "Village",
                "village tamil name",
                "Firka",
                "Taluk",
                "District",
            ]
        )
        for row in rows:
            sheet.append(row)
        book.save(path)
        book.close()
        return path

    def test_import_defaults_to_dry_run(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [
                    [1, "Sasikumar", "Kedar", "கேடார்", "F", "T", "D"],
                ],
            )
            out = StringIO()
            call_command("import_operational_villages", str(path), stdout=out)
            text = out.getvalue()
        self.assertIn("DRY RUN ZERO WRITES: YES", text)
        self.assertEqual(Village.objects.count(), 0)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 0)

    def test_import_dedupes_village_and_assigns_shared(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [
                    [1, "Sasikumar", "Madagadipattu", "மடகடிப்பட்டு", "F", "T", "D"],
                    [2, "Kaviyarasan", "Madagadipattu", "மடகடிப்பட்டு", "F", "T", "D"],
                    [3, "Sasikumar", " kedar ", "கேடார்", "F", "T", "D"],
                    [4, "Sasikumar", "Kedar", "கேடார்", "F", "T", "D"],
                ],
            )
            call_command("import_operational_villages", str(path), "--execute")

        self.assertEqual(Village.objects.count(), 2)
        mad = Village.objects.get(name="Madagadipattu")
        self.assertIsNone(mad.district_id)
        self.assertIsNone(mad.taluk_id)
        self.assertEqual(mad.name_ta, "மடகடிப்பட்டு")
        kedar = Village.objects.get(name__iexact="kedar")
        self.assertEqual(kedar.name_ta, "கேடார்")

        self.assertEqual(EmployeeLocationAssignment.objects.count(), 3)
        sasi_villages = set(
            EmployeeLocationAssignment.objects.filter(
                employee=self.sasi_profile, is_operational=True
            ).values_list("village__name", flat=True)
        )
        self.assertEqual(sasi_villages, {"Madagadipattu", "kedar"})
        self.assertTrue(
            EmployeeLocationAssignment.objects.filter(
                employee=self.kavi_profile, village=mad, is_operational=True
            ).exists()
        )
        for row in EmployeeLocationAssignment.objects.all():
            self.assertIsNone(row.district_id)
            self.assertIsNone(row.taluk_id)
            self.assertTrue(row.is_operational)

    def test_import_idempotent(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [[1, "Sasikumar", "Kedar", "கேடார்", "F", "T", "D"]],
            )
            call_command("import_operational_villages", str(path), "--execute")
            call_command("import_operational_villages", str(path), "--execute")
        self.assertEqual(Village.objects.count(), 1)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 1)

    def test_tamil_conflict_blocks_execute(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [
                    [1, "Sasikumar", "Manaveli", "மணவேலி", "F", "T", "D"],
                    [2, "Kaviyarasan", "Manaveli", "மனவேலி", "F", "T", "D"],
                ],
            )
            out = StringIO()
            call_command("import_operational_villages", str(path), stdout=out)
            self.assertIn("TAMIL_NAME_CONFLICT", out.getvalue())
            with self.assertRaises(CommandError):
                call_command("import_operational_villages", str(path), "--execute")
        self.assertEqual(Village.objects.count(), 0)

    def test_employee_not_found_blocks_execute(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [[1, "UnknownStaff", "Kedar", "கேடார்", "F", "T", "D"]],
            )
            with self.assertRaises(CommandError):
                call_command("import_operational_villages", str(path), "--execute")
        self.assertEqual(Village.objects.count(), 0)

    def test_blank_tamil_allowed(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [[1, "Sasikumar", "BlankTamilVillage", "", "F", "T", "D"]],
            )
            call_command("import_operational_villages", str(path), "--execute")
        village = Village.objects.get(name="BlankTamilVillage")
        self.assertEqual(village.name_ta, "")

    def test_blank_plus_nonblank_tamil_uses_nonblank(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [
                    [1, "Sasikumar", "SharedTamil", "", "F", "T", "D"],
                    [2, "Kaviyarasan", "SharedTamil", "தமிழ்", "F", "T", "D"],
                ],
            )
            out = StringIO()
            call_command("import_operational_villages", str(path), stdout=out)
            self.assertNotIn("TAMIL_NAME_CONFLICT", out.getvalue())
            call_command("import_operational_villages", str(path), "--execute")
        village = Village.objects.get(name="SharedTamil")
        self.assertEqual(village.name_ta, "தமிழ்")

    def test_missing_village_reported_not_blocking_dry_run(self):
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [
                    [1, "Sasikumar", "", "தமிழ்", "F", "T", "D"],
                    [2, "Sasikumar", "Kedar", "கேடார்", "F", "T", "D"],
                ],
            )
            out = StringIO()
            call_command("import_operational_villages", str(path), stdout=out)
            text = out.getvalue()
        self.assertIn("INVALID_MISSING_VILLAGE", text)
        self.assertIn("TOTAL VALID EXCEL ROWS: 1", text)
        self.assertEqual(Village.objects.count(), 0)

    def test_expected_employee_id_mismatch_blocks_execute(self):
        self.sasi_profile.employee_id = "WRONG-ID"
        self.sasi_profile.save(update_fields=["employee_id"])
        with TemporaryDirectory() as tmp:
            path = self._write_workbook(
                tmp,
                [[1, "Sasikumar", "Kedar", "கேடார்", "F", "T", "D"]],
            )
            out = StringIO()
            call_command("import_operational_villages", str(path), stdout=out)
            self.assertIn("EMPLOYEE_ID_MISMATCH", out.getvalue())
            with self.assertRaises(CommandError):
                call_command("import_operational_villages", str(path), "--execute")
        self.assertEqual(Village.objects.count(), 0)
