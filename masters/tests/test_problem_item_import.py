import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.test import APIClient

from masters.models import Crop, ProblemCategory, ProblemMaster


def _build_pest_workbook(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Crop", "English Pest Name", "Tamil Pest Name"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        "pest_and_diseases.xlsx",
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class ProblemItemImportTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_pi",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.pest_category, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "requires_problem_master": True},
        )
        self.disease_category, _ = ProblemCategory.objects.get_or_create(
            code="disease",
            defaults={"name": "Disease", "requires_problem_master": True},
        )

    def test_import_pest_excel(self):
        upload = _build_pest_workbook(
            [
                ("Rice", "Stem borer", "தண்டு துளைப்பான்"),
                ("Tomato", "Fruit worm", "பழப் புழு"),
            ]
        )
        r = self.client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        data = r.data["data"]
        self.assertEqual(data["imported_count"], 2)
        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(
            data["warning"], "Disease data not found in uploaded file"
        )
        self.assertIn("Disease data not found in uploaded file", data["warnings"])
        self.assertEqual(ProblemMaster.objects.filter(category=self.pest_category).count(), 2)
        item = ProblemMaster.objects.get(name="Stem borer")
        self.assertEqual(item.tamil_name, "தண்டு துளைப்பான்")
        self.assertEqual(item.category_id, self.pest_category.id)

    def test_crop_auto_creation(self):
        before = Crop.objects.count()
        upload = _build_pest_workbook([("New Crop XYZ", "Aphid", "அஃபிட்")])
        r = self.client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Crop.objects.count(), before + 1)
        crop = Crop.objects.get(name_en="New Crop XYZ")
        self.assertTrue(
            ProblemMaster.objects.filter(crop=crop, name="Aphid").exists()
        )

    def test_duplicate_prevention_and_tamil_update(self):
        crop = Crop.objects.create(name_en="Rice", name_ta="Rice")
        ProblemMaster.objects.create(
            category=self.pest_category,
            crop=crop,
            name="Stem borer",
            tamil_name="",
        )
        upload = _build_pest_workbook([("Rice", "Stem borer", "தண்டு துளைப்பான்")])
        r = self.client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        data = r.data["data"]
        self.assertEqual(data["updated_count"], 1)
        self.assertEqual(data["imported_count"], 0)
        item = ProblemMaster.objects.get(name="Stem borer")
        self.assertEqual(item.tamil_name, "தண்டு துளைப்பான்")

    def test_duplicate_with_tamil_already_set_is_skipped(self):
        crop = Crop.objects.create(name_en="Rice", name_ta="Rice")
        ProblemMaster.objects.create(
            category=self.pest_category,
            crop=crop,
            name="Stem borer",
            tamil_name="existing",
        )
        upload = _build_pest_workbook([("Rice", "Stem borer", "தண்டு துளைப்பான்")])
        r = self.client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["data"]["skipped_duplicates"], 1)

    def test_missing_required_columns_error(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Crop", "Name"])
        ws.append(["Rice", "Stem borer"])
        buffer = io.BytesIO()
        wb.save(buffer)
        upload = SimpleUploadedFile(
            "bad_columns.xlsx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        r = self.client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("Missing required columns", str(r.data))

    def test_invalid_row_reported(self):
        upload = _build_pest_workbook([("", "Stem borer", "தமிழ்")])
        r = self.client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("Crop is required", str(r.data))

    def test_problem_items_list_api(self):
        crop = Crop.objects.create(name_en="Rice", name_ta="நெல்")
        ProblemMaster.objects.create(
            category=self.pest_category,
            crop=crop,
            name="Stem borer",
            tamil_name="தமிழ்",
        )
        r = self.client.get("/api/v1/problem-items/?category=pest")
        self.assertEqual(r.status_code, 200, r.data)
        results = r.data["data"]["results"]
        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["name"], "Stem borer")
        self.assertEqual(row["tamil_name"], "தமிழ்")
        self.assertEqual(row["category"], "pest")
        self.assertEqual(row["crop"], crop.id)
        self.assertEqual(row["crop_name"], "Rice")

    def test_crop_nested_problem_items_filter(self):
        rice = Crop.objects.create(name_en="Rice", name_ta="Rice")
        tomato = Crop.objects.create(name_en="Tomato", name_ta="Tomato")
        ProblemMaster.objects.create(
            category=self.pest_category, crop=rice, name="Stem borer"
        )
        ProblemMaster.objects.create(
            category=self.disease_category, crop=rice, name="Blast"
        )
        ProblemMaster.objects.create(
            category=self.pest_category, crop=tomato, name="Fruit worm"
        )
        r = self.client.get(f"/api/v1/crops/{rice.id}/problem-items/?category=pest")
        self.assertEqual(r.status_code, 200, r.data)
        names = {row["name"] for row in r.data["data"]["results"]}
        self.assertEqual(names, {"Stem borer"})

    def test_masters_import_requires_staff(self):
        user = User.objects.create_user(username="emp_pi", password="x")
        client = APIClient()
        client.force_authenticate(user=user)
        upload = _build_pest_workbook([("Rice", "Aphid", "அஃபிட்")])
        r = client.post(
            "/api/v1/masters/problem-masters/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(r.status_code, 403, r.data)

    def test_admin_manual_create(self):
        crop = Crop.objects.create(name_en="Rice", name_ta="Rice")
        r = self.client.post(
            "/api/v1/admin/problem-items/",
            {
                "name": "Leaf hopper",
                "tamil_name": "இலை குதிப்பான்",
                "category": "pest",
                "crop": crop.id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["data"]["category"], "pest")
