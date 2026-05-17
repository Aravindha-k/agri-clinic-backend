from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit


class AuditAgriDataCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="audit_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.user,
            employee_id="EMP-AUDIT-CMD",
            phone="9000000777",
            is_active_employee=True,
        )
        district = District.objects.create(name="Cmd District")
        village = Village.objects.create(name="Cmd Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Real Farmer",
            phone="9111222333",
            district=district,
            village=village,
            is_active=True,
        )
        Farmer.objects.create(
            name="E2E Test Farmer",
            phone="9090909090",
            district=district,
            village=village,
            is_active=False,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        Visit.objects.create(
            employee=self.user,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.0,
            longitude=77.0,
            farmer_name=self.farmer.name,
        )
        Visit.objects.create(
            employee=self.user,
            status="pending",
            farmer_name="Orphan",
        )

    def test_audit_command_runs(self):
        out = StringIO()
        call_command("audit_agri_data", stdout=out)
        text = out.getvalue()
        self.assertIn("total farmers", text)
        self.assertIn("submitted valid", text)

    def test_clean_dry_run_does_not_delete(self):
        before_f = Farmer.objects.count()
        before_v = Visit.objects.count()
        call_command("clean_test_agri_data", "--dry-run", stdout=StringIO())
        self.assertEqual(Farmer.objects.count(), before_f)
        self.assertEqual(Visit.objects.count(), before_v)

    def test_seed_demo_visits_idempotent(self):
        from farmers.management.commands.seed_real_demo_visits import (
            demo_sync_id,
        )

        out = StringIO()
        call_command("seed_real_demo_visits", "--confirm", stdout=out)
        count_after_first = Visit.objects.filter(
            local_sync_id=demo_sync_id(self.farmer.id)
        ).count()
        self.assertEqual(count_after_first, 1)
        call_command("seed_real_demo_visits", "--confirm", stdout=StringIO())
        self.assertEqual(
            Visit.objects.filter(local_sync_id=demo_sync_id(self.farmer.id)).count(),
            1,
        )
