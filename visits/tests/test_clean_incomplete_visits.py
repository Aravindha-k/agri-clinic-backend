from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from masters.models import Crop, District, Farmer, Village
from visits.models import Visit
from visits.submitted import get_visit_cleanup_counts, incomplete_visits_qs


class CleanIncompleteVisitsCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cleanup_emp", password="x")
        district = District.objects.create(name="Cleanup District")
        village = Village.objects.create(name="Cleanup Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Cleanup Farmer",
            phone="9444444444",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Wheat", name_ta="Wheat", is_active=True)

        self.submitted = Visit.objects.create(
            employee=self.user,
            farmer=self.farmer,
            crop=self.crop,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=village,
            latitude=12.0,
            longitude=77.0,
        )
        # No name/phone — post_save sync must not auto-create a Farmer row.
        self.no_farmer = Visit.objects.create(
            employee=self.user,
            crop=self.crop,
            latitude=12.1,
            longitude=77.1,
        )
        self.missing_gps = Visit.objects.create(
            employee=self.user,
            farmer=self.farmer,
            crop=self.crop,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=village,
            latitude=None,
            longitude=None,
        )

    def test_counts_classify_submitted_vs_incomplete(self):
        counts = get_visit_cleanup_counts()
        self.assertEqual(counts["total_visits"], 3)
        self.assertEqual(counts["submitted_visits"], 1)
        self.assertEqual(counts["incomplete_visits"], 2)
        self.assertEqual(counts["no_farmer"], 1)
        self.assertEqual(counts["missing_gps"], 1)

    def test_dry_run_does_not_delete(self):
        out = StringIO()
        call_command("clean_incomplete_visits", stdout=out)
        self.assertEqual(Visit.objects.count(), 3)
        self.assertTrue(Visit.objects.filter(pk=self.submitted.pk).exists())
        self.assertEqual(incomplete_visits_qs().count(), 2)
        self.assertIn("Dry-run", out.getvalue())
        self.assertIn("would delete 2", out.getvalue())

    def test_confirm_deletes_only_incomplete(self):
        farmer_count_before = Farmer.objects.count()
        out = StringIO()
        call_command("clean_incomplete_visits", "--confirm", stdout=out)
        self.assertEqual(Visit.objects.count(), 1)
        self.assertTrue(Visit.objects.filter(pk=self.submitted.pk).exists())
        self.assertFalse(Visit.objects.filter(pk=self.no_farmer.pk).exists())
        self.assertFalse(Visit.objects.filter(pk=self.missing_gps.pk).exists())
        self.assertEqual(Farmer.objects.count(), farmer_count_before)
        after = get_visit_cleanup_counts()
        self.assertEqual(after["submitted_visits"], 1)
        self.assertEqual(after["incomplete_visits"], 0)
        self.assertIn("Deleted", out.getvalue())
