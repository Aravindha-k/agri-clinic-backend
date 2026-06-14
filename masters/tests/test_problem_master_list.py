from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from masters.models import Crop, ProblemCategory, ProblemMaster


class ProblemMasterListAPITest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_pm_list",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "requires_problem_master": True},
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice")
        ProblemMaster.objects.create(
            category=self.category,
            crop=self.crop,
            name="Stem borer",
            tamil_name="tamil",
        )

    def test_admin_problem_masters_list_uses_success_envelope(self):
        r = self.client.get("/api/v1/admin/problem-masters/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data.get("success"))
        self.assertIn("data", r.data)
        rows = r.data["data"]
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "pest")
        self.assertEqual(rows[0]["category_code"], "pest")

    def test_masters_problem_masters_category_filter(self):
        r = self.client.get("/api/v1/masters/problem-masters/?category=pest")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreaterEqual(len(r.data["data"]), 1)
        self.assertEqual(r.data["data"][0]["category"], "pest")

    def test_admin_problem_masters_category_code_filter(self):
        r = self.client.get("/api/v1/admin/problem-masters/?category=pest")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreaterEqual(len(r.data["data"]), 1)
        self.assertEqual(r.data["data"][0]["category"], "pest")
