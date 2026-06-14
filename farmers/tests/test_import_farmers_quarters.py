import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from farmers.tests.test_clean_and_import_farmers import _write_quarter_workbook
from masters.models import District, Farmer, Village
from visits.models import Visit


class ImportFarmersQuartersMergeTest(TestCase):
    def setUp(self):
        self.district = District.objects.create(name="Villupuram", is_active=True)
        self.village = Village.objects.create(
            name="Ananthapuram", district=self.district, is_active=True
        )
        self.existing = Farmer.objects.create(
            name="Kanagaraj Ananthapuram",
            phone="9688953207",
            district=self.district,
            village=self.village,
            state="Tamil Nadu",
            source_quarter="quarter1",
            source_file="QUARTER 1GrpSum.xlsx",
            is_active=True,
        )

    def test_merge_dry_run_does_not_change_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            q3 = Path(tmp) / "QUARTER 3GrpSum.xlsx"
            q4 = Path(tmp) / "QUARTER 4GrpSum.xlsx"
            _write_quarter_workbook(q3)
            _write_quarter_workbook(q4)
            out = StringIO()
            call_command(
                "import_farmers_quarters",
                "--merge",
                "--dry-run",
                f"--quarter3={q3}",
                f"--quarter4={q4}",
                stdout=out,
            )
        self.assertEqual(Farmer.objects.count(), 1)
        text = out.getvalue()
        self.assertIn("Merge preview", text)
        self.assertIn("Dry-run only", text)
        self.assertIn("Duplicate farmers expected", text)

    def test_merge_import_creates_new_and_updates_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            q3 = Path(tmp) / "QUARTER 3GrpSum.xlsx"
            q4 = Path(tmp) / "QUARTER 4GrpSum.xlsx"
            _write_quarter_workbook(q3)
            _write_quarter_workbook(q4)
            backup_file = Path(tmp) / "backup.sql"
            backup_file.write_text("-- test backup", encoding="utf-8")
            out = StringIO()
            with patch(
                "farmers.management.commands.import_farmers_quarters.create_db_backup",
                return_value=backup_file,
            ):
                call_command(
                    "import_farmers_quarters",
                    "--merge",
                    "--confirm",
                    f"--quarter3={q3}",
                    f"--quarter4={q4}",
                    stdout=out,
                )

        self.assertTrue(Farmer.objects.filter(name="Test Farmer").exists() is False)
        self.assertEqual(Farmer.objects.count(), 4)
        self.existing.refresh_from_db()
        self.assertIn("quarter3", self.existing.source_quarter)
        self.assertIn("quarter1", self.existing.source_quarter)
        self.assertEqual(self.existing.state, "Tamil Nadu")

        text = out.getvalue()
        self.assertIn("Merge import complete.", text)
        json_start = text.rfind('{\n  "farmers_before"')
        self.assertGreater(json_start, -1)
        summary = json.loads(text[json_start:])
        self.assertEqual(summary["farmers_before"], 1)
        self.assertEqual(summary["farmers_created"], 3)
        self.assertGreaterEqual(summary["farmers_updated"], 1)

    def test_merge_does_not_delete_visits(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user("agent", password="pass")
        Visit.objects.create(
            farmer=self.existing,
            employee=user,
            farmer_name=self.existing.name,
            farmer_phone=self.existing.phone,
            status="submitted",
        )
        with tempfile.TemporaryDirectory() as tmp:
            q3 = Path(tmp) / "QUARTER 3GrpSum.xlsx"
            _write_quarter_workbook(q3)
            backup_file = Path(tmp) / "backup.sql"
            backup_file.write_text("-- test backup", encoding="utf-8")
            out = StringIO()
            with patch(
                "farmers.management.commands.import_farmers_quarters.create_db_backup",
                return_value=backup_file,
            ):
                call_command(
                    "import_farmers_quarters",
                    "--merge",
                    "--confirm",
                    f"--quarter3={q3}",
                    stdout=out,
                )
        self.assertEqual(Visit.objects.count(), 1)
