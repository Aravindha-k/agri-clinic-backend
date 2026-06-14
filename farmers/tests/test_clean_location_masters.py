from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from masters.models import District, Farmer, Village


class CleanLocationMastersTest(TestCase):
    def setUp(self):
        self.keep_district = District.objects.create(name="Villupuram", is_active=True)
        self.remove_district = District.objects.create(name="Coimbatore", is_active=True)
        self.keep_village = Village.objects.create(
            name="Agaram", district=self.keep_district, is_active=True
        )
        self.remove_village = Village.objects.create(
            name="Annur", district=self.remove_district, is_active=True
        )
        Farmer.objects.create(
            name="Chandran Agaram",
            phone="9000000099",
            district=self.keep_district,
            village=self.keep_village,
            state="Tamil Nadu",
            source_quarter="quarter1",
            is_active=True,
        )

    def test_dry_run_lists_orphans(self):
        out = StringIO()
        call_command("clean_location_masters", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("Coimbatore", text)
        self.assertIn("Annur", text)
        self.assertIn("Dry-run only", text)

    def test_confirm_removes_unused_locations(self):
        backup = Path(__file__).parent / "tmp_backup.sql"
        backup.write_text("-- test", encoding="utf-8")
        out = StringIO()
        with patch(
            "farmers.management.commands.clean_location_masters.create_db_backup",
            return_value=backup,
        ):
            call_command("clean_location_masters", "--confirm", stdout=out)
        self.assertTrue(District.objects.filter(name="Villupuram").exists())
        self.assertFalse(District.objects.filter(name="Coimbatore").exists())
        self.assertTrue(Village.objects.filter(name="Agaram").exists())
        self.assertFalse(Village.objects.filter(name="Annur").exists())
        self.assertEqual(Farmer.objects.count(), 1)
        backup.unlink(missing_ok=True)
