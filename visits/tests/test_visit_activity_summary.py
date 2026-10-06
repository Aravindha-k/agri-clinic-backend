"""Admin Field Visits management activity-summary endpoint."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, Farmer, ProblemCategory, Village
from visits.models import Visit


class VisitActivitySummaryTests(APITestCase):
    url = "/api/v1/admin/visits/activity-summary/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_act_sum",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        # Deliberately diverge EmployeeProfile.pk from User.pk (separate sequences
        # plus a spacer profile so the contract cannot accidentally match).
        spacer = User.objects.create_user(username="spacer_act", password="x")
        EmployeeProfile.objects.create(
            user=spacer,
            employee_id="KAC-SPACER",
            phone="9000000099",
            is_active_employee=False,
            can_login=False,
        )
        spacer.is_active = False
        spacer.save(update_fields=["is_active"])

        self.emp_a = User.objects.create_user(
            username="act_a", password="x", first_name="Kaviyarasan"
        )
        self.emp_b = User.objects.create_user(
            username="act_b", password="x", first_name="Sasikumar"
        )
        self.emp_c = User.objects.create_user(
            username="act_c", password="x", first_name="ZeroVisits"
        )
        self.profile_a = EmployeeProfile.objects.create(
            user=self.emp_a,
            employee_id="KAC-0003",
            phone="9000000001",
            is_active_employee=True,
            can_login=True,
        )
        self.profile_b = EmployeeProfile.objects.create(
            user=self.emp_b,
            employee_id="KAC-0004",
            phone="9000000002",
            is_active_employee=True,
            can_login=True,
        )
        self.profile_c = EmployeeProfile.objects.create(
            user=self.emp_c,
            employee_id="KAC-0005",
            phone="9000000003",
            is_active_employee=True,
            can_login=True,
        )
        self.assertNotEqual(
            self.profile_a.pk,
            self.emp_a.pk,
            msg="Fixture must keep Profile.pk ≠ User.pk",
        )

        # Inactive field employee — must not appear in roster.
        self.emp_inactive = User.objects.create_user(
            username="act_inactive", password="x", first_name="Inactive"
        )
        self.emp_inactive.is_active = False
        self.emp_inactive.save(update_fields=["is_active"])
        EmployeeProfile.objects.create(
            user=self.emp_inactive,
            employee_id="KAC-0099",
            phone="9000000098",
            is_active_employee=False,
            can_login=False,
        )

        # Staff with a profile — not a field employee.
        self.staff_user = User.objects.create_user(
            username="act_staff", password="x", first_name="Staffer", is_staff=True
        )
        EmployeeProfile.objects.create(
            user=self.staff_user,
            employee_id="KAC-STAFF",
            phone="9000000097",
            is_active_employee=True,
            can_login=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        self.village = Village.objects.create(name="Act Village")
        self.farmer = Farmer.objects.create(
            name="Act Farmer", phone="9333000101", village=self.village
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.category = ProblemCategory.objects.create(
            name="Act Summary Category",
            code="act_summary_cat",
            is_active=True,
            requires_problem_master=False,
        )
        self.today = timezone.localdate()
        self.other_day = self.today - timedelta(days=3)
        self.week_start = self.today - timedelta(days=self.today.weekday())
        self.month_start = self.today.replace(day=1)
        # A day inside the month but before "today" when possible; else week_start.
        if self.today.day > 1:
            self.mid_month = self.today - timedelta(days=1)
            if self.mid_month < self.month_start:
                self.mid_month = self.month_start
        else:
            self.mid_month = self.today
        # Prefer a distinct earlier day in-range for latest_visit_at tests.
        self.in_week_earlier = self.week_start
        if self.in_week_earlier == self.today:
            self.in_week_earlier = self.today  # Monday-only week edge

        # emp_a: 2 submitted GPS visits today (staggered created_at)
        self.v_a1 = self._legacy_visit(self.emp_a, self.today)
        self.v_a2 = self._legacy_visit(self.emp_a, self.today)
        older = timezone.now() - timedelta(hours=2)
        newer = timezone.now() - timedelta(minutes=5)
        Visit.objects.filter(pk=self.v_a1.pk).update(created_at=older)
        Visit.objects.filter(pk=self.v_a2.pk).update(created_at=newer)
        self.v_a2.refresh_from_db()

        # emp_b: 1 submitted GPS visit today + 1 without GPS (field-visit path)
        self.v_b1 = self._legacy_visit(self.emp_b, self.today)
        self.v_b_no_gps = self._field_visit_no_gps(self.emp_b, self.today)

        # Outside date — excluded from today; included in broader ranges when in week/month
        self.v_a_other = self._legacy_visit(self.emp_a, self.other_day)
        Visit.objects.filter(pk=self.v_a_other.pk).update(
            created_at=timezone.now() - timedelta(days=3, hours=1)
        )
        self.v_a_other.refresh_from_db()

        # Extra in-range visits for week/month coverage (skip if they collapse to today)
        self.v_b_week = None
        if self.in_week_earlier != self.today:
            self.v_b_week = self._legacy_visit(self.emp_b, self.in_week_earlier)
            Visit.objects.filter(pk=self.v_b_week.pk).update(
                created_at=timezone.now() - timedelta(days=2)
            )
            self.v_b_week.refresh_from_db()

        self.v_a_mid = None
        if self.mid_month != self.today and self.mid_month != self.other_day:
            self.v_a_mid = self._legacy_visit(self.emp_a, self.mid_month)
            Visit.objects.filter(pk=self.v_a_mid.pk).update(
                created_at=timezone.now() - timedelta(hours=12)
            )
            self.v_a_mid.refresh_from_db()

        # Incomplete — excluded
        Visit.objects.create(
            employee=self.emp_a,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            visit_date=self.today,
        )

        # Inactive employee visit today — must not inflate totals
        self._legacy_visit(self.emp_inactive, self.today)

        # Staff visit today — must not inflate totals / roster
        self._legacy_visit(self.staff_user, self.today)

        # After-range visit (future) — must stay excluded from ranges ending today
        self.after_day = self.today + timedelta(days=2)
        self.v_a_future = self._legacy_visit(self.emp_a, self.after_day)

    def _legacy_visit(self, emp, visit_date, **extra):
        return Visit.objects.create(
            employee=emp,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            crop=self.crop,
            latitude=11.0,
            longitude=78.0,
            village=self.village,
            visit_date=visit_date,
            **extra,
        )

    def _field_visit_no_gps(self, emp, visit_date):
        return Visit.objects.create(
            employee=emp,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            crop=self.crop,
            village=self.village,
            problem_category=self.category,
            land_area=1.5,
            problem_description="Leaf damage observed",
            visit_date=visit_date,
            latitude=None,
            longitude=None,
        )

    def _get(self, **params):
        return self.client.get(self.url, params)

    def test_admin_can_access(self):
        r = self._get(date=self.today.isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["success"])
        self.assertEqual(r.data["data"]["date"], self.today.isoformat())

    def test_unauthenticated_rejected(self):
        c = APIClient()
        r = c.get(self.url, {"date": self.today.isoformat()})
        self.assertIn(r.status_code, (401, 403))

    def test_non_admin_field_employee_rejected(self):
        c = APIClient()
        c.force_authenticate(user=self.emp_a)
        r = c.get(self.url, {"date": self.today.isoformat()})
        self.assertEqual(r.status_code, 403)

    def test_totals_and_per_employee_counts(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        # eligible: A,B,C (spacer/inactive/staff excluded)
        # visits: A=2, B=2 (1 gps + 1 no gps) = 4
        self.assertEqual(data["total_visits"], 4)
        self.assertEqual(data["active_staff"], 2)
        self.assertEqual(data["no_visits"], 1)
        self.assertEqual(data["gps_verified"], 3)

        by_code = {e["employee_id"]: e for e in data["employees"]}
        self.assertEqual(set(by_code), {"KAC-0003", "KAC-0004", "KAC-0005"})
        self.assertEqual(by_code["KAC-0003"]["visit_count"], 2)
        self.assertEqual(by_code["KAC-0004"]["visit_count"], 2)
        self.assertEqual(by_code["KAC-0005"]["visit_count"], 0)
        self.assertIsNone(by_code["KAC-0005"]["latest_visit_at"])

    def test_user_id_is_auth_user_pk_not_profile_pk(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        by_code = {e["employee_id"]: e for e in data["employees"]}
        self.assertEqual(by_code["KAC-0003"]["user_id"], self.emp_a.pk)
        self.assertNotEqual(by_code["KAC-0003"]["user_id"], self.profile_a.pk)
        self.assertEqual(by_code["KAC-0003"]["employee_id"], "KAC-0003")

    def test_latest_visit_at_is_max_created_at(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        by_code = {e["employee_id"]: e for e in data["employees"]}
        latest = by_code["KAC-0003"]["latest_visit_at"]
        self.assertIsNotNone(latest)
        # DRF may return datetime or ISO string
        if isinstance(latest, str):
            from django.utils.dateparse import parse_datetime

            latest = parse_datetime(latest)
        self.assertEqual(latest, self.v_a2.created_at)

    def test_outside_date_and_incomplete_excluded(self):
        data = self._get(date=self.other_day.isoformat()).data["data"]
        self.assertEqual(data["total_visits"], 1)
        self.assertEqual(data["active_staff"], 1)
        by_code = {e["employee_id"]: e for e in data["employees"]}
        self.assertEqual(by_code["KAC-0003"]["visit_count"], 1)
        self.assertEqual(by_code["KAC-0004"]["visit_count"], 0)
        self.assertEqual(by_code["KAC-0005"]["visit_count"], 0)

    def test_inactive_and_staff_excluded_from_roster(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        codes = {e["employee_id"] for e in data["employees"]}
        self.assertNotIn("KAC-0099", codes)
        self.assertNotIn("KAC-STAFF", codes)
        self.assertNotIn("KAC-SPACER", codes)

    def test_invalid_date_400(self):
        r = self._get(date="not-a-date")
        self.assertEqual(r.status_code, 400)

    def test_missing_date_400(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 400)

    def test_ordering_visit_count_desc_then_name(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        codes = [e["employee_id"] for e in data["employees"]]
        # A and B both have 2; name Kaviyarasan before Sasikumar; zero last
        self.assertEqual(codes, ["KAC-0003", "KAC-0004", "KAC-0005"])

    def test_query_count_bounded(self):
        # Warm auth / contenttypes caches then assert a small fixed query budget.
        self._get(date=self.today.isoformat())
        with CaptureQueriesContext(connection) as ctx:
            r = self._get(date=self.today.isoformat())
        self.assertEqual(r.status_code, 200)
        # Roster + per-employee annotate + totals aggregate + bulk DutySession
        # for single-day duty enrichment (+ optional session).
        self.assertLessEqual(len(ctx), 10)

    def test_single_day_range_equals_date_metrics(self):
        by_date = self._get(date=self.today.isoformat()).data["data"]
        by_range = self._get(
            start_date=self.today.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        self.assertEqual(by_range["start_date"], self.today.isoformat())
        self.assertEqual(by_range["end_date"], self.today.isoformat())
        self.assertNotIn("date", by_range)
        for key in ("total_visits", "active_staff", "no_visits", "gps_verified"):
            self.assertEqual(by_range[key], by_date[key])
        self.assertEqual(
            [(e["employee_id"], e["visit_count"]) for e in by_range["employees"]],
            [(e["employee_id"], e["visit_count"]) for e in by_date["employees"]],
        )

    def test_multi_day_range_includes_other_day(self):
        data = self._get(
            start_date=self.other_day.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        # today: A2 + B2 = 4; other_day: A1 → 5 (+ optional mid/week extras)
        by_code = {e["employee_id"]: e for e in data["employees"]}
        self.assertGreaterEqual(by_code["KAC-0003"]["visit_count"], 3)  # 2 today + 1 other
        self.assertEqual(data["active_staff"], 2)
        self.assertEqual(data["no_visits"], 1)
        self.assertIn("KAC-0005", by_code)
        self.assertEqual(by_code["KAC-0005"]["visit_count"], 0)
        self.assertIsNone(by_code["KAC-0005"]["latest_visit_at"])

    def test_week_range_counts(self):
        data = self._get(
            start_date=self.week_start.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        self.assertEqual(data["start_date"], self.week_start.isoformat())
        self.assertEqual(data["end_date"], self.today.isoformat())
        by_code = {e["employee_id"]: e for e in data["employees"]}
        # Always includes today's A=2, B=2
        expected_a = 2
        expected_b = 2
        if self.other_day >= self.week_start:
            expected_a += 1
        if self.v_b_week is not None:
            expected_b += 1
        if self.v_a_mid is not None and self.mid_month >= self.week_start:
            expected_a += 1
        self.assertEqual(by_code["KAC-0003"]["visit_count"], expected_a)
        self.assertEqual(by_code["KAC-0004"]["visit_count"], expected_b)
        self.assertEqual(by_code["KAC-0005"]["visit_count"], 0)
        self.assertEqual(data["total_visits"], expected_a + expected_b)
        self.assertEqual(data["active_staff"], 2)
        self.assertEqual(data["no_visits"], 1)

    def test_month_range_counts(self):
        data = self._get(
            start_date=self.month_start.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        self.assertEqual(data["start_date"], self.month_start.isoformat())
        self.assertEqual(data["end_date"], self.today.isoformat())
        by_code = {e["employee_id"]: e for e in data["employees"]}
        expected_a = 2
        expected_b = 2
        if self.other_day >= self.month_start:
            expected_a += 1
        if self.v_b_week is not None and self.in_week_earlier >= self.month_start:
            expected_b += 1
        if self.v_a_mid is not None:
            expected_a += 1
        self.assertEqual(by_code["KAC-0003"]["visit_count"], expected_a)
        self.assertEqual(by_code["KAC-0004"]["visit_count"], expected_b)
        self.assertEqual(data["total_visits"], expected_a + expected_b)
        self.assertEqual(data["gps_verified"], expected_a + expected_b - 1)  # one no-gps

    def test_range_latest_visit_at_within_range(self):
        data = self._get(
            start_date=self.other_day.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        by_code = {e["employee_id"]: e for e in data["employees"]}
        latest = by_code["KAC-0003"]["latest_visit_at"]
        if isinstance(latest, str):
            from django.utils.dateparse import parse_datetime

            latest = parse_datetime(latest)
        self.assertEqual(latest, self.v_a2.created_at)

    def test_range_excludes_before_and_after(self):
        # Range that is only other_day → excludes today and future
        data = self._get(
            start_date=self.other_day.isoformat(),
            end_date=self.other_day.isoformat(),
        ).data["data"]
        self.assertEqual(data["total_visits"], 1)
        by_code = {e["employee_id"]: e for e in data["employees"]}
        self.assertEqual(by_code["KAC-0003"]["visit_count"], 1)
        self.assertEqual(by_code["KAC-0004"]["visit_count"], 0)

        # Ending today excludes future visit
        data_today = self._get(
            start_date=self.today.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        self.assertEqual(data_today["total_visits"], 4)

    def test_range_user_pk_contract_unchanged(self):
        data = self._get(
            start_date=self.week_start.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        by_code = {e["employee_id"]: e for e in data["employees"]}
        self.assertEqual(by_code["KAC-0003"]["user_id"], self.emp_a.pk)
        self.assertNotEqual(by_code["KAC-0003"]["user_id"], self.profile_a.pk)

    def test_range_inactive_staff_excluded(self):
        data = self._get(
            start_date=self.month_start.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        codes = {e["employee_id"] for e in data["employees"]}
        self.assertNotIn("KAC-0099", codes)
        self.assertNotIn("KAC-STAFF", codes)

    def test_start_after_end_400(self):
        r = self._get(
            start_date=self.today.isoformat(),
            end_date=self.other_day.isoformat(),
        )
        self.assertEqual(r.status_code, 400)

    def test_malformed_range_dates_400(self):
        r = self._get(start_date="bad", end_date=self.today.isoformat())
        self.assertEqual(r.status_code, 400)
        r2 = self._get(start_date=self.today.isoformat(), end_date="14-10-2026")
        self.assertEqual(r2.status_code, 400)

    def test_incomplete_range_400(self):
        r = self._get(start_date=self.today.isoformat())
        self.assertEqual(r.status_code, 400)
        r2 = self._get(end_date=self.today.isoformat())
        self.assertEqual(r2.status_code, 400)

    def test_date_plus_range_ambiguous_400(self):
        r = self._get(
            date=self.today.isoformat(),
            start_date=self.today.isoformat(),
            end_date=self.today.isoformat(),
        )
        self.assertEqual(r.status_code, 400)

    def test_range_query_count_bounded(self):
        self._get(
            start_date=self.month_start.isoformat(),
            end_date=self.today.isoformat(),
        )
        with CaptureQueriesContext(connection) as ctx:
            r = self._get(
                start_date=self.month_start.isoformat(),
                end_date=self.today.isoformat(),
            )
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(ctx), 8)
