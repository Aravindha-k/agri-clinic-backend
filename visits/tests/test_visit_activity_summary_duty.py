"""Activity-summary Today duty aggregation (DutySession bulk)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, Farmer, ProblemCategory, Village
from tracking.duty_timer import (
    COMPLETION_AUTO_EXPIRED,
    COMPLETION_MANUAL,
    DURATION_LIMIT_SECONDS,
)
from tracking.models import DutySession, WorkDay
from visits.activity_duty import (
    STATUS_AUTO_ENDED,
    STATUS_ENDED,
    STATUS_NOT_STARTED,
    STATUS_ON_DUTY,
    aggregate_employee_duty,
)
from visits.models import Visit


def _make_field_employee(*, username: str, employee_id: str, first_name: str = "") -> User:
    user = User.objects.create_user(
        username=username, password="x", first_name=first_name or username
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000" + employee_id[-3:],
        is_active_employee=True,
        can_login=True,
    )
    return user


def _duty(
    user: User,
    *,
    start,
    end=None,
    is_active=True,
    auto_ended=False,
    completion_reason=None,
    business_date=None,
):
    business_date = business_date or timezone.localdate(start)
    wd = WorkDay.objects.create(
        user=user,
        date=business_date,
        start_time=start,
        end_time=end,
        is_active=is_active,
        auto_ended=auto_ended,
    )
    return DutySession.objects.create(
        user=user,
        workday=wd,
        date=business_date,
        start_time=start,
        end_time=end,
        is_active=is_active,
        auto_ended=auto_ended,
        completion_reason=completion_reason,
    )


@override_settings(TIME_ZONE="Asia/Kolkata")
class AggregateEmployeeDutyUnitTests(TestCase):
    def setUp(self):
        self.user = _make_field_employee(username="duty_u", employee_id="KAC-D01")
        self.now = timezone.now().replace(microsecond=0)

    def test_no_sessions_not_started(self):
        payload = aggregate_employee_duty([], now=self.now)
        self.assertEqual(payload["status"], STATUS_NOT_STARTED)
        self.assertEqual(payload["session_count"], 0)
        self.assertEqual(payload["duration_seconds"], 0)
        self.assertIsNone(payload["start_time"])

    def test_active_duty_duration_capped(self):
        start = self.now - timedelta(hours=10)
        duty = _duty(self.user, start=start, is_active=True)
        payload = aggregate_employee_duty([duty], now=self.now)
        self.assertEqual(payload["status"], STATUS_ON_DUTY)
        self.assertEqual(payload["duration_seconds"], DURATION_LIMIT_SECONDS)
        self.assertIsNone(payload["end_time"])
        self.assertEqual(payload["duration_limit_seconds"], DURATION_LIMIT_SECONDS)

    def test_completed_manual_duty(self):
        start = self.now - timedelta(hours=3)
        end = start + timedelta(hours=2, minutes=30)
        duty = _duty(
            self.user,
            start=start,
            end=end,
            is_active=False,
            completion_reason=COMPLETION_MANUAL,
        )
        payload = aggregate_employee_duty([duty], now=self.now)
        self.assertEqual(payload["status"], STATUS_ENDED)
        self.assertEqual(payload["completion_reason"], COMPLETION_MANUAL)
        self.assertEqual(payload["duration_seconds"], 2 * 3600 + 30 * 60)
        self.assertEqual(payload["end_time"], end.isoformat())

    def test_auto_ended_duty(self):
        start = self.now - timedelta(hours=9)
        end = start + timedelta(seconds=DURATION_LIMIT_SECONDS)
        duty = _duty(
            self.user,
            start=start,
            end=end,
            is_active=False,
            auto_ended=True,
            completion_reason=COMPLETION_AUTO_EXPIRED,
        )
        payload = aggregate_employee_duty([duty], now=self.now)
        self.assertEqual(payload["status"], STATUS_AUTO_ENDED)
        self.assertEqual(payload["duration_seconds"], DURATION_LIMIT_SECONDS)

    def test_multiple_sessions_sum_duration(self):
        first_start = self.now - timedelta(hours=5)
        first_end = first_start + timedelta(hours=1)
        second_start = first_end + timedelta(minutes=30)
        first = _duty(
            self.user,
            start=first_start,
            end=first_end,
            is_active=False,
            completion_reason=COMPLETION_MANUAL,
        )
        second = _duty(
            self.user,
            start=second_start,
            is_active=True,
        )
        payload = aggregate_employee_duty([second, first], now=self.now)
        self.assertEqual(payload["status"], STATUS_ON_DUTY)
        self.assertEqual(payload["session_count"], 2)
        self.assertEqual(payload["start_time"], first_start.isoformat())
        expected = 3600 + int((self.now - second_start).total_seconds())
        self.assertEqual(payload["duration_seconds"], expected)


@override_settings(TIME_ZONE="Asia/Kolkata")
class VisitActivitySummaryDutyAPITests(APITestCase):
    url = "/api/v1/admin/visits/activity-summary/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_duty_act",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        spacer = User.objects.create_user(username="spacer_duty_act", password="x")
        EmployeeProfile.objects.create(
            user=spacer,
            employee_id="KAC-DSP",
            phone="9000000888",
            is_active_employee=False,
            can_login=False,
        )
        spacer.is_active = False
        spacer.save(update_fields=["is_active"])

        self.emp_a = _make_field_employee(
            username="duty_act_a", employee_id="KAC-0003", first_name="Kaviyarasan"
        )
        self.emp_b = _make_field_employee(
            username="duty_act_b", employee_id="KAC-0004", first_name="Sasikumar"
        )
        self.emp_c = _make_field_employee(
            username="duty_act_c", employee_id="KAC-0005", first_name="ZeroVisits"
        )
        self.profile_a = EmployeeProfile.objects.get(user=self.emp_a)
        self.assertNotEqual(self.profile_a.pk, self.emp_a.pk)

        self.emp_inactive = User.objects.create_user(
            username="duty_act_inactive", password="x", first_name="Inactive"
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

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        self.village = Village.objects.create(name="Duty Act Village")
        self.farmer = Farmer.objects.create(
            name="Duty Act Farmer", phone="9333000202", village=self.village
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        ProblemCategory.objects.create(
            name="Duty Act Category",
            code="duty_act_cat",
            is_active=True,
            requires_problem_master=False,
        )
        self.today = timezone.localdate()
        self.now = timezone.now().replace(microsecond=0)

        Visit.objects.create(
            employee=self.emp_a,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            crop=self.crop,
            latitude=11.0,
            longitude=78.0,
            village=self.village,
            visit_date=self.today,
        )

    def _get(self, **params):
        return self.client.get(self.url, params)

    def _by_code(self, data):
        return {e["employee_id"]: e for e in data["employees"]}

    def test_not_started_when_no_duty(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        emp = self._by_code(data)["KAC-0005"]
        self.assertEqual(emp["visit_count"], 0)
        self.assertEqual(emp["duty"]["status"], STATUS_NOT_STARTED)
        self.assertEqual(emp["duty"]["session_count"], 0)

    def test_active_duty_on_today(self):
        start = self.now - timedelta(hours=2, minutes=35)
        _duty(self.emp_b, start=start, is_active=True)
        with patch("visits.activity_duty.timezone.now", return_value=self.now):
            data = self._get(date=self.today.isoformat()).data["data"]
        emp = self._by_code(data)["KAC-0004"]
        self.assertEqual(emp["duty"]["status"], STATUS_ON_DUTY)
        self.assertEqual(emp["duty"]["duration_seconds"], 2 * 3600 + 35 * 60)
        self.assertIsNone(emp["duty"]["end_time"])
        self.assertEqual(emp["user_id"], self.emp_b.pk)

    def test_zero_visits_with_active_duty(self):
        start = self.now - timedelta(minutes=40)
        _duty(self.emp_c, start=start, is_active=True)
        with patch("visits.activity_duty.timezone.now", return_value=self.now):
            data = self._get(date=self.today.isoformat()).data["data"]
        emp = self._by_code(data)["KAC-0005"]
        self.assertEqual(emp["visit_count"], 0)
        self.assertEqual(emp["duty"]["status"], STATUS_ON_DUTY)

    def test_visits_with_no_duty(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        emp = self._by_code(data)["KAC-0003"]
        self.assertGreaterEqual(emp["visit_count"], 1)
        self.assertEqual(emp["duty"]["status"], STATUS_NOT_STARTED)

    def test_completed_and_auto_ended(self):
        start_a = self.now - timedelta(hours=4)
        end_a = start_a + timedelta(hours=3)
        _duty(
            self.emp_a,
            start=start_a,
            end=end_a,
            is_active=False,
            completion_reason=COMPLETION_MANUAL,
        )
        start_b = self.now - timedelta(hours=9)
        end_b = start_b + timedelta(seconds=DURATION_LIMIT_SECONDS)
        _duty(
            self.emp_b,
            start=start_b,
            end=end_b,
            is_active=False,
            auto_ended=True,
            completion_reason=COMPLETION_AUTO_EXPIRED,
        )
        data = self._get(date=self.today.isoformat()).data["data"]
        by_code = self._by_code(data)
        self.assertEqual(by_code["KAC-0003"]["duty"]["status"], STATUS_ENDED)
        self.assertEqual(by_code["KAC-0003"]["duty"]["duration_seconds"], 3 * 3600)
        self.assertEqual(by_code["KAC-0004"]["duty"]["status"], STATUS_AUTO_ENDED)
        self.assertEqual(
            by_code["KAC-0004"]["duty"]["duration_seconds"], DURATION_LIMIT_SECONDS
        )

    def test_multiple_sessions_same_day(self):
        first_start = self.now - timedelta(hours=5)
        first_end = first_start + timedelta(hours=1)
        second_start = first_end + timedelta(minutes=15)
        _duty(
            self.emp_a,
            start=first_start,
            end=first_end,
            is_active=False,
            completion_reason=COMPLETION_MANUAL,
        )
        _duty(self.emp_a, start=second_start, is_active=True)
        with patch("visits.activity_duty.timezone.now", return_value=self.now):
            data = self._get(date=self.today.isoformat()).data["data"]
        duty = self._by_code(data)["KAC-0003"]["duty"]
        self.assertEqual(duty["status"], STATUS_ON_DUTY)
        self.assertEqual(duty["session_count"], 2)
        self.assertEqual(duty["start_time"], first_start.isoformat())
        self.assertEqual(
            duty["duration_seconds"],
            3600 + int((self.now - second_start).total_seconds()),
        )

    def test_user_pk_contract_unchanged(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        emp = self._by_code(data)["KAC-0003"]
        self.assertEqual(emp["user_id"], self.emp_a.pk)
        self.assertNotEqual(emp["user_id"], self.profile_a.pk)

    def test_inactive_excluded(self):
        _duty(self.emp_inactive, start=self.now - timedelta(hours=1), is_active=True)
        data = self._get(date=self.today.isoformat()).data["data"]
        codes = {e["employee_id"] for e in data["employees"]}
        self.assertNotIn("KAC-0099", codes)

    def test_existing_fields_present(self):
        data = self._get(date=self.today.isoformat()).data["data"]
        for key in ("total_visits", "active_staff", "no_visits", "gps_verified", "employees"):
            self.assertIn(key, data)
        emp = data["employees"][0]
        for key in ("user_id", "employee_id", "name", "visit_count", "latest_visit_at", "duty"):
            self.assertIn(key, emp)

    def test_multi_day_range_duty_is_null(self):
        _duty(self.emp_a, start=self.now - timedelta(hours=1), is_active=True)
        start = (self.today - timedelta(days=2)).isoformat()
        end = self.today.isoformat()
        data = self._get(start_date=start, end_date=end).data["data"]
        for emp in data["employees"]:
            self.assertIsNone(emp["duty"])

    def test_single_day_range_includes_duty(self):
        _duty(self.emp_a, start=self.now - timedelta(hours=1), is_active=True)
        data = self._get(
            start_date=self.today.isoformat(),
            end_date=self.today.isoformat(),
        ).data["data"]
        emp = self._by_code(data)["KAC-0003"]
        self.assertEqual(emp["duty"]["status"], STATUS_ON_DUTY)

    def test_permission_staff_admin(self):
        c = APIClient()
        c.force_authenticate(user=self.emp_a)
        r = c.get(self.url, {"date": self.today.isoformat()})
        self.assertEqual(r.status_code, 403)
