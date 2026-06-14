from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class CleanTestDataCommandTest(TestCase):
    def test_dry_run_lists_delete_tables(self):
        out = StringIO()
        call_command("clean_test_data", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("=== A. KEEP", text)
        self.assertIn("=== B. DELETE", text)
        self.assertIn("masters_problemmaster", text)
        self.assertIn("visits_visit", text)
        self.assertIn("masters_farmer", text)
        self.assertIn("auth_user_field_agents", text)
        self.assertIn("Dry-run only", text)
        self.assertNotIn("Cleanup complete", text)
