"""Tests for reset_operational_data — preserve accounts, wipe operational rows."""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.models import (
    Crop,
    CropIssue,
    District,
    Farmer,
    FarmerActivity,
    FarmerField,
    FieldCrop,
    ProblemCategory,
    ProblemMaster,
    Recommendation,
    Taluk,
    Village,
)
from mobile_api.test_helpers import assign_operational_territory, login_mobile_client
from reports.models import Report
from system_settings.operational_reset import CONFIRM_PHRASE
from tracking.models import DutySession, EmployeeGpsState, EmployeeRoutePoint, WorkDay
from visits.models import Visit, VisitAttachment, VisitMedia

STRONG = "SecurePass1!"
EMP_PASSWORD = "EmployeePass1!"


class ResetOperationalDataCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="reset_admin",
            password=STRONG,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        EmployeeProfile.objects.create(
            user=self.admin,
            employee_id="ADM-RESET",
            phone="9000000100",
            role="Supervisor",
        )
        self.employee = User.objects.create_user(
            username="reset_emp",
            password=EMP_PASSWORD,
            is_staff=False,
            first_name="Sasikumar",
        )
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="KAC-RESET01",
            phone="9000000200",
            role="FieldAgent",
            is_active_employee=True,
            can_login=True,
        )
        self.admin_password_hash = self.admin.password
        self.employee_password_hash = self.employee.password

        self.district_old = District.objects.create(name="Old District")
        self.taluk_old = Taluk.objects.create(
            name="Old Taluk", district=self.district_old
        )
        self.village_old = Village.objects.create(
            name="Old Village",
            district=self.district_old,
            taluk=self.taluk_old,
        )
        self.profile.district = self.district_old
        self.profile.village = self.village_old
        self.profile.save(update_fields=["district", "village"])
        assign_operational_territory(self.employee, self.village_old)

        self.crop = Crop.objects.create(name_en="Paddy", name_ta="Paddy", is_active=True)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "requires_problem_master": True},
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category,
            name="Stem borer",
            crop=self.crop,
        )

        self.farmer = Farmer.objects.create(
            name="Legacy Farmer",
            phone="9111000999",
            district=self.district_old,
            taluk=self.taluk_old,
            village=self.village_old,
            assigned_employee=self.employee,
        )
        self.field = FarmerField.objects.create(
            farmer=self.farmer,
            land_name="Legacy Land",
            land_size="1.00",
        )
        FieldCrop.objects.create(land=self.field, crop_name="Paddy", crop=self.crop)
        FarmerActivity.objects.create(
            farmer=self.farmer,
            activity_type="FARMER_CREATED",
            created_by=self.employee,
        )

        self.visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=self.village_old,
            district=self.district_old,
            crop=self.crop,
            land_area=1.0,
            problem_category=self.category,
            problem_master=self.problem,
            problem_description="Legacy issue",
            latitude=12.0,
            longitude=79.0,
        )
        issue = CropIssue.objects.create(
            visit=self.visit, crop=self.crop, description="Legacy crop issue"
        )
        Recommendation.objects.create(issue=issue, given_by=self.employee, notes="spray")
        VisitMedia.objects.create(
            visit=self.visit,
            uploaded_by=self.employee,
            file=ContentFile(b"img", name="legacy.jpg"),
            media_type=VisitMedia.MEDIA_TYPE_IMAGE,
        )
        VisitAttachment.objects.create(
            visit=self.visit,
            employee=self.employee,
            attachment_type="image",
            file=ContentFile(b"att", name="legacy-att.jpg"),
        )
        Report.objects.create(
            requested_by=self.admin,
            report_type="visit_summary",
            status=Report.STATUS_DONE,
        )

        started = datetime(2026, 1, 1, 8, 0, tzinfo=dt_timezone.utc)
        workday = WorkDay.objects.create(
            user=self.employee,
            date=date(2026, 1, 1),
            start_time=started,
            is_active=False,
        )
        duty = DutySession.objects.create(
            user=self.employee,
            workday=workday,
            date=date(2026, 1, 1),
            start_time=started,
            is_active=False,
        )
        EmployeeRoutePoint.objects.create(
            user=self.employee,
            duty_session=duty,
            latitude=12.0,
            longitude=79.0,
            recorded_at=started,
            visit_id=self.visit.id,
            farmer_id=self.farmer.id,
        )
        EmployeeGpsState.objects.create(
            user=self.employee,
            gps_enabled=True,
            location_permission_status="granted",
        )

    def _execute(self):
        out = StringIO()
        call_command(
            "reset_operational_data",
            "--execute",
            f"--confirm-phrase={CONFIRM_PHRASE}",
            stdout=out,
        )
        return out.getvalue()

    def test_default_is_dry_run_and_deletes_nothing(self):
        out = StringIO()
        call_command("reset_operational_data", stdout=out)
        text = out.getvalue()
        self.assertIn("DRY RUN", text)
        self.assertIn("--- PRESERVE ---", text)
        self.assertIn("--- DELETE ---", text)
        self.assertIn("Dry-run only", text)
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())
        self.assertTrue(Visit.objects.filter(pk=self.visit.pk).exists())
        self.assertTrue(District.objects.filter(pk=self.district_old.pk).exists())
        self.assertTrue(
            EmployeeLocationAssignment.objects.filter(employee=self.profile).exists()
        )
        self.assertIn("DRY RUN ZERO WRITES VERIFIED: YES", text)
        self.assertEqual(Farmer.objects.count(), 1)
        self.assertEqual(Village.objects.count(), 1)
        self.assertEqual(EmployeeProfile.objects.count(), 2)

    def test_execute_without_phrase_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("reset_operational_data", "--execute")
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())

    def test_execute_with_wrong_phrase_is_refused(self):
        with self.assertRaises(CommandError):
            call_command(
                "reset_operational_data",
                "--execute",
                "--confirm-phrase=please-delete",
            )
        self.assertTrue(Visit.objects.filter(pk=self.visit.pk).exists())

    def test_production_dry_run_is_allowed(self):
        with patch(
            "system_settings.management.commands.reset_operational_data.is_production_env",
            return_value=True,
        ):
            out = StringIO()
            call_command("reset_operational_data", stdout=out)
        self.assertIn("DRY RUN ZERO WRITES VERIFIED: YES", out.getvalue())
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())

    def test_production_execute_requires_allow_flag(self):
        with patch(
            "system_settings.management.commands.reset_operational_data.is_production_env",
            return_value=True,
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "reset_operational_data",
                    "--execute",
                    f"--confirm-phrase={CONFIRM_PHRASE}",
                )
        self.assertIn("production", str(ctx.exception).lower())
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())

    def test_execute_preserves_accounts_and_clears_operational_rows(self):
        self._execute()

        self.admin.refresh_from_db()
        self.employee.refresh_from_db()
        self.profile.refresh_from_db()

        self.assertTrue(User.objects.filter(pk=self.admin.pk, is_staff=True).exists())
        self.assertTrue(User.objects.filter(pk=self.employee.pk).exists())
        self.assertTrue(EmployeeProfile.objects.filter(pk=self.profile.pk).exists())
        self.assertEqual(self.profile.employee_id, "KAC-RESET01")
        self.assertEqual(self.admin.password, self.admin_password_hash)
        self.assertEqual(self.employee.password, self.employee_password_hash)
        self.assertTrue(check_password(STRONG, self.admin.password))
        self.assertTrue(check_password(EMP_PASSWORD, self.employee.password))
        self.assertIsNone(self.profile.district_id)
        self.assertIsNone(self.profile.village_id)

        self.assertEqual(District.objects.count(), 0)
        self.assertEqual(Taluk.objects.count(), 0)
        self.assertEqual(Village.objects.count(), 0)
        self.assertEqual(EmployeeLocationAssignment.objects.count(), 0)
        self.assertEqual(Farmer.objects.count(), 0)
        self.assertEqual(FarmerField.objects.count(), 0)
        self.assertEqual(FieldCrop.objects.count(), 0)
        self.assertEqual(FarmerActivity.objects.count(), 0)
        self.assertEqual(Visit.objects.count(), 0)
        self.assertEqual(VisitMedia.objects.count(), 0)
        self.assertEqual(VisitAttachment.objects.count(), 0)
        self.assertEqual(CropIssue.objects.count(), 0)
        self.assertEqual(Recommendation.objects.count(), 0)
        self.assertEqual(DutySession.objects.count(), 0)
        self.assertEqual(WorkDay.objects.count(), 0)
        self.assertEqual(EmployeeRoutePoint.objects.count(), 0)
        self.assertEqual(EmployeeGpsState.objects.count(), 0)
        self.assertEqual(Report.objects.count(), 0)

        self.assertTrue(Crop.objects.filter(pk=self.crop.pk).exists())
        self.assertTrue(ProblemCategory.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(ProblemMaster.objects.filter(pk=self.problem.pk).exists())

        admin_login = APIClient().post(
            "/api/v1/auth/login/",
            {"username": "reset_admin", "password": STRONG},
            format="json",
        )
        self.assertEqual(admin_login.status_code, status.HTTP_200_OK, admin_login.data)

        mobile = login_mobile_client(
            employee_id="KAC-RESET01", password=EMP_PASSWORD
        )
        territory = mobile.get("/api/v1/mobile/territory/")
        self.assertEqual(territory.status_code, status.HTTP_200_OK, territory.data)
        self.assertEqual(territory.data["data"]["villages"], [])

    def test_new_territory_farmer_visit_flow_after_reset(self):
        self._execute()

        district_a = District.objects.create(name="District A")
        taluk_a = Taluk.objects.create(name="Taluk A", district=district_a)
        village_a1 = Village.objects.create(
            name="Village A1", district=district_a, taluk=taluk_a
        )
        village_a2 = Village.objects.create(
            name="Village A2", district=district_a, taluk=taluk_a
        )
        assign_operational_territory(self.employee, village_a1)

        client = login_mobile_client(
            employee_id="KAC-RESET01", password=EMP_PASSWORD
        )
        territory = client.get("/api/v1/mobile/territory/")
        self.assertEqual(territory.status_code, status.HTTP_200_OK, territory.data)
        villages = territory.data["data"]["villages"]
        self.assertEqual({v["name"] for v in villages}, {"Village A1"})
        self.assertNotIn("Village A2", {v["name"] for v in villages})
        self.assertEqual(village_a2.name, "Village A2")

        create_farmer = client.post(
            "/api/v1/farmers/",
            {
                "name": "Fresh Farmer",
                "phone": "9222000001",
                "village": village_a1.id,
            },
            format="json",
        )
        self.assertEqual(
            create_farmer.status_code, status.HTTP_201_CREATED, create_farmer.data
        )
        farmer = Farmer.objects.get(phone="9222000001")
        self.assertEqual(farmer.village_id, village_a1.id)
        self.assertIsNone(farmer.taluk_id)
        self.assertIsNone(farmer.district_id)

        visit_resp = client.post(
            "/api/v1/mobile/visits/",
            {
                "farmer_name": "Fresh Farmer",
                "phone_number": "9222000001",
                "village_id": village_a1.id,
                "crop_id": self.crop.id,
                "acreage": 1.5,
                "problem_category_id": self.category.id,
                "problem_master_id": self.problem.id,
                "problem_description": "Fresh operational visit after reset.",
            },
            format="json",
        )
        self.assertEqual(visit_resp.status_code, status.HTTP_200_OK, visit_resp.data)
        self.assertEqual(Visit.objects.count(), 1)
        visit = Visit.objects.get()
        self.assertEqual(visit.farmer_id, farmer.id)
        self.assertEqual(visit.village_id, village_a1.id)
        self.assertEqual(visit.employee_id, self.employee.id)
