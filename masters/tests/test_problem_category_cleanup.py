from django.contrib.auth.models import User
from django.core.management import call_command
from io import StringIO

from django.test import TestCase
from rest_framework.test import APIClient

from masters.models import Crop, ProblemCategory, ProblemMaster
from masters.problem_category_cleanup import (
    audit_problem_categories,
    deactivate_unused_problem_categories,
)


class ProblemCategoryCleanupTest(TestCase):
    def setUp(self):
        self.pest, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "is_active": True},
        )
        self.disease, _ = ProblemCategory.objects.get_or_create(
            code="disease",
            defaults={"name": "Disease", "is_active": True},
        )
        self.legacy = ProblemCategory.objects.create(
            code="pest_attack",
            name="Pest Attack",
            is_active=True,
        )
        crop = Crop.objects.create(name_en="Rice", name_ta="Rice")
        ProblemMaster.objects.create(
            category=self.pest, crop=crop, name="Stem borer", is_active=True
        )

    def test_audit_identifies_zero_item_categories(self):
        audit = audit_problem_categories()
        codes = {row["code"] for row in audit["zero_item_categories"]}
        self.assertIn("disease", codes)
        self.assertIn("pest_attack", codes)
        keep_codes = {row["code"] for row in audit["categories_to_keep"]}
        self.assertEqual(keep_codes, {"pest"})

    def test_deactivate_unused_categories(self):
        result = deactivate_unused_problem_categories(dry_run=False)
        self.assertGreaterEqual(result.deactivated_count, 2)
        self.disease.refresh_from_db()
        self.legacy.refresh_from_db()
        self.assertFalse(self.disease.is_active)
        self.assertFalse(self.legacy.is_active)
        self.pest.refresh_from_db()
        self.assertTrue(self.pest.is_active)

    def test_dropdown_returns_only_categories_with_items(self):
        deactivate_unused_problem_categories(dry_run=False)
        admin = User.objects.create_superuser("admin_pc", "a@t.com", "pass")
        client = APIClient()
        client.force_authenticate(user=admin)
        r = client.get(
            "/api/v1/masters/problem-categories/dropdown/",
            HTTP_HOST="localhost",
        )
        self.assertEqual(r.status_code, 200, r.data)
        codes = [row["code"] for row in r.data["data"]]
        self.assertEqual(codes, ["pest"])

    def test_problem_items_search_all_when_crop_empty(self):
        crop = Crop.objects.first()
        other_crop = Crop.objects.create(name_en="Tomato", name_ta="Tomato")
        ProblemMaster.objects.create(
            category=self.pest,
            crop=other_crop,
            name="Fruit worm",
            is_active=True,
        )
        admin = User.objects.create_superuser("admin_pc2", "b@t.com", "pass")
        client = APIClient()
        client.force_authenticate(user=admin)
        r = client.get(
            f"/api/v1/problem-items/?category=pest&crop_id={crop.id}"
            "&search=Fruit&search_all=true",
            HTTP_HOST="localhost",
        )
        self.assertEqual(r.status_code, 200, r.data)
        names = {row["name"] for row in r.data["data"]["results"]}
        self.assertIn("Fruit worm", names)

    def test_management_command_dry_run(self):
        out = StringIO()
        call_command("clean_problem_categories", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("Dry-run only", text)
        self.assertIn("Pest Attack", text)
