"""Admin Village + Employee assignment Excel import API tests."""

from __future__ import annotations

from io import BytesIO

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.models import Village
from masters.operational_village_import import collect_plan, execute_plan

STRONG = "SecurePass1!"
VALIDATE_URL = "/api/v1/admin/villages/import/validate/"
CONFIRM_URL = "/api/v1/admin/villages/import/confirm/"


def _workbook_bytes(headers: list[str], rows: list[list]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buf = BytesIO()
    book.save(buf)
    book.close()
    return buf.getvalue()


def _xlsx_upload(headers: list[str], rows: list[list], name: str = "villages.xlsx"):
    return SimpleUploadedFile(
        name,
        _workbook_bytes(headers, rows),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class VillageImportApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="import_admin", password=STRONG, is_staff=True
        )
        self.user = User.objects.create_user(
            username="import_user", password=STRONG, is_staff=False
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        self.sasi_user = User.objects.create_user(
            username="sasi", password=STRONG, first_name="Sasikumar"
        )
        self.sasi = EmployeeProfile.objects.create(
            user=self.sasi_user,
            employee_id="KAC-0004",
            phone="9000000001",
            role="FieldAgent",
        )
        self.kavi_user = User.objects.create_user(
            username="kavi", password=STRONG, first_name="Kaviyarasan"
        )
        self.kavi = EmployeeProfile.objects.create(
            user=self.kavi_user,
            employee_id="KAC-0003",
            phone="9000000002",
            role="FieldAgent",
        )

    def _canonical(self, rows):
        return _xlsx_upload(
            ["Employee ID", "Employee Name", "Village", "Village Tamil Name"],
            rows,
        )

    def _legacy(self, rows):
        return _xlsx_upload(
            ["S NO", "Field staff", "Village", "village tamil name", "Firka", "Taluk", "District"],
            rows,
        )

    def test_unauthorized_user(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            VALIDATE_URL,
            {"file": self._canonical([["KAC-0004", "Sasikumar", "Kedar", "கேடார்"]])},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_extension(self):
        upload = SimpleUploadedFile("villages.csv", b"a,b\n1,2", content_type="text/csv")
        resp = self.client.post(VALIDATE_URL, {"file": upload}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json().get("code"), "INVALID_EXTENSION")

    def test_malformed_workbook(self):
        upload = SimpleUploadedFile(
            "villages.xlsx",
            b"not-an-xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp = self.client.post(VALIDATE_URL, {"file": upload}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json().get("code"), "MALFORMED_WORKBOOK")

    def test_missing_headers(self):
        upload = _xlsx_upload(["Foo", "Bar"], [["a", "b"]])
        resp = self.client.post(VALIDATE_URL, {"file": upload}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json().get("code"), "MISSING_HEADERS")

    def test_validation_makes_zero_writes(self):
        resp = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [["KAC-0004", "Sasikumar", "NewVillage", "தமிழ்"]]
                )
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(Village.objects.count(), 0)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 0)
        data = resp.json()["data"]
        self.assertTrue(data["can_confirm"])
        self.assertTrue(data["import_token"])

    def test_new_village_confirm(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [["KAC-0004", "Sasikumar", "BrandNew", "புதிய"]]
                )
            },
            format="multipart",
        )
        token = validate.json()["data"]["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK, confirm.data)
        body = confirm.json()["data"]
        self.assertEqual(body["villages_created"], 1)
        self.assertEqual(body["assignments_created"], 1)
        village = Village.objects.get(name="BrandNew")
        self.assertEqual(village.name_ta, "புதிய")
        self.assertIsNone(village.district_id)
        self.assertTrue(
            EmployeeLocationAssignment.objects.filter(
                employee=self.sasi, village=village, is_operational=True
            ).exists()
        )

    def test_existing_village_reused(self):
        Village.objects.create(name="Kedar", name_ta="கேடார்")
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [["KAC-0004", "Sasikumar", "kedar", ""]]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(data["villages_to_create"], 0)
        self.assertEqual(data["villages_existing"], 1)
        token = data["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK, confirm.data)
        self.assertEqual(Village.objects.filter(name__iexact="kedar").count(), 1)
        self.assertEqual(confirm.json()["data"]["assignments_created"], 1)

    def test_english_only_and_blank_tamil(self):
        validate = self.client.post(
            VALIDATE_URL,
            {"file": self._canonical([["", "", "EnglishOnly", ""]])},
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(data["tamil_names_blank"], 1)
        token = data["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        village = Village.objects.get(name="EnglishOnly")
        self.assertEqual(village.name_ta, "")
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 0)

    def test_tamil_village_and_case_insensitive_duplicate(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [
                        ["KAC-0004", "Sasikumar", "Kedar", "கேடார்"],
                        ["KAC-0003", "Kaviyarasan", " KEDAR ", "கேடார்"],
                    ]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(data["unique_villages"], 1)
        self.assertEqual(data["assignments_to_create"], 2)
        token = data["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertEqual(Village.objects.count(), 1)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 2)

    def test_shared_village_two_employees(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [
                        ["KAC-0004", "Sasikumar", "Madagadipattu", "மட"],
                        ["KAC-0003", "Kaviyarasan", "Madagadipattu", "மட"],
                    ]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(len(data["shared_villages"]), 1)
        token = data["import_token"]
        self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        village = Village.objects.get(name="Madagadipattu")
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(village=village).count(), 2
        )

    def test_duplicate_employee_village_idempotent(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [
                        ["KAC-0004", "Sasikumar", "Kedar", "கேடார்"],
                        ["KAC-0004", "Sasikumar", "Kedar", "கேடார்"],
                    ]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(data["assignments_to_create"], 1)
        token = data["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.json()["data"]["assignments_created"], 1)
        # Replay confirm with same token must fail (consumed/deleted)
        replay = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(replay.json().get("code"), {"TOKEN_REPLAY", "TOKEN_INVALID"})
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 1)

    def test_confirmation_idempotent_second_import(self):
        upload_rows = [["KAC-0004", "Sasikumar", "Kedar", "கேடார்"]]
        v1 = self.client.post(
            VALIDATE_URL, {"file": self._canonical(upload_rows)}, format="multipart"
        )
        self.client.post(
            CONFIRM_URL, {"import_token": v1.json()["data"]["import_token"]}, format="json"
        )
        v2 = self.client.post(
            VALIDATE_URL, {"file": self._canonical(upload_rows)}, format="multipart"
        )
        data = v2.json()["data"]
        self.assertEqual(data["villages_to_create"], 0)
        self.assertEqual(data["assignments_to_create"], 0)
        self.assertEqual(data["assignments_existing"], 1)
        c2 = self.client.post(
            CONFIRM_URL, {"import_token": data["import_token"]}, format="json"
        )
        self.assertEqual(c2.status_code, status.HTTP_200_OK)
        self.assertEqual(c2.json()["data"]["assignments_created"], 0)
        self.assertEqual(Village.objects.count(), 1)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 1)

    def test_employee_id_matching(self):
        validate = self.client.post(
            VALIDATE_URL,
            {"file": self._canonical([["KAC-0003", "", "Semmedu", ""]])},
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertTrue(any("KAC-0003" in m for m in data["employees_matched"]))
        token = data["import_token"]
        self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertTrue(
            EmployeeLocationAssignment.objects.filter(employee=self.kavi).exists()
        )

    def test_legacy_field_staff_name_matching(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._legacy(
                    [[1, "Sasikumar", "Pillaiyarkuppam", "பிள்ளை", "F", "T", "D"]]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertTrue(data["warnings"])
        self.assertTrue(any("NAME_BASED" in w or "name-based" in w for w in data["warnings"]))
        token = data["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertTrue(
            EmployeeLocationAssignment.objects.filter(employee=self.sasi).exists()
        )

    def test_employee_not_found(self):
        validate = self.client.post(
            VALIDATE_URL,
            {"file": self._canonical([["KAC-9999", "Nobody", "Kedar", ""]])},
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertIn("EMPLOYEE_NOT_FOUND", data["blocking_errors"])
        self.assertIsNone(data["import_token"])
        self.assertEqual(Village.objects.count(), 0)

    def test_ambiguous_employee(self):
        User.objects.create_user(username="sasi2", password=STRONG, first_name="Sasikumar")
        EmployeeProfile.objects.create(
            user=User.objects.get(username="sasi2"),
            employee_id="KAC-0099",
            phone="9000000099",
            role="FieldAgent",
        )
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._legacy(
                    [[1, "Sasikumar", "Kedar", "கேடார்", "F", "T", "D"]]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertIn("AMBIGUOUS_EMPLOYEE", data["blocking_errors"])
        self.assertIsNone(data["import_token"])

    def test_employee_id_name_mismatch(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [["KAC-0004", "Kaviyarasan", "Kedar", "கேடார்"]]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertIn("EMPLOYEE_MISMATCH", data["blocking_errors"])
        self.assertIsNone(data["import_token"])

    def test_tamil_conflict(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [
                        ["KAC-0004", "Sasikumar", "Manaveli", "மணவெளி"],
                        ["KAC-0003", "Kaviyarasan", "Manaveli", "மனவெளி"],
                    ]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertIn("TAMIL_NAME_CONFLICT", data["blocking_errors"])
        self.assertEqual(len(data["tamil_name_conflicts"]), 1)
        self.assertIsNone(data["import_token"])

    def test_blank_plus_nonblank_tamil_ok(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [
                        ["KAC-0004", "Sasikumar", "Shared", ""],
                        ["KAC-0003", "Kaviyarasan", "Shared", "தமிழ்"],
                    ]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertNotIn("TAMIL_NAME_CONFLICT", data["blocking_errors"])
        token = data["import_token"]
        self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(Village.objects.get(name="Shared").name_ta, "தமிழ்")

    def test_empty_village_reported(self):
        validate = self.client.post(
            VALIDATE_URL,
            {
                "file": self._canonical(
                    [
                        ["KAC-0004", "Sasikumar", "", "தமிழ்"],
                        ["KAC-0004", "Sasikumar", "OkVillage", ""],
                    ]
                )
            },
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(data["valid_rows"], 1)
        self.assertTrue(any("INVALID_MISSING_VILLAGE" in e for e in data["errors"]))
        # Missing village alone does not block confirm of valid rows
        self.assertTrue(data["can_confirm"])
        token = data["import_token"]
        confirm = self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertEqual(Village.objects.count(), 1)

    def test_empty_employee_village_only(self):
        validate = self.client.post(
            VALIDATE_URL,
            {"file": self._canonical([["", "", "SoloVillage", "தனி"]])},
            format="multipart",
        )
        data = validate.json()["data"]
        self.assertEqual(data["assignments_to_create"], 0)
        token = data["import_token"]
        self.client.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(Village.objects.get(name="SoloVillage").name_ta, "தனி")
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 0)

    def test_confirm_transaction_rollback_on_blocking(self):
        # Build a plan then inject blocking error before execute via service
        upload = self._canonical([["KAC-0004", "Sasikumar", "RollbackVille", ""]])
        plan = collect_plan(upload)
        plan.blocking_errors.append("TAMIL_NAME_CONFLICT")
        with self.assertRaises(Exception):
            execute_plan(plan)
        self.assertEqual(Village.objects.count(), 0)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 0)

    def test_confirm_rejects_client_fabricated_token(self):
        resp = self.client.post(
            CONFIRM_URL, {"import_token": "not-a-real-token"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json().get("code"), "TOKEN_INVALID")
        self.assertEqual(Village.objects.count(), 0)
