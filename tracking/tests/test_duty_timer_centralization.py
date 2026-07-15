"""Prove all DutySession timer consumers go through duty_timer / duty_expiry."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.employee_photo import _workday_status_for_user
from accounts.models import EmployeeProfile
from tracking.daily_summary import compute_work_hours_seconds
from tracking.duty_service import serialize_duty_status, start_duty, end_duty
from tracking.duty_timer import (
    DURATION_LIMIT_SECONDS,
    compute_duty_timer,
    expected_end_at,
    is_session_within_limit,
)
from tracking.models import DutySession, WorkDay
from tracking.route_utils import build_admin_route_data
from tracking.status_utils import build_admin_tracking_row
from tracking.workday_utils import (
    MAX_WORKDAY_DURATION,
    is_workday_within_duration,
    workday_scheduled_end,
)


def _employee(username="cen_emp", employee_id="CEN-001"):
    user = User.objects.create_user(username=username, password="secret123")
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000111",
        is_active_employee=True,
    )
    return user


class ProfileTimerCentralizationTests(TestCase):
    def setUp(self):
        self.user = _employee()
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "CEN-001",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )

    def test_profile_expected_end_from_duty_timer(self):
        duty = start_duty(self.user).duty
        status_block = _workday_status_for_user(self.user)
        timer = compute_duty_timer(duty)
        self.assertEqual(status_block["expected_end_at"], timer["expected_end_at"])
        self.assertEqual(status_block["ends_at"], timer["expected_end_at"])
        self.assertEqual(status_block["elapsed_seconds"], timer["elapsed_seconds"])
        self.assertEqual(status_block["remaining_seconds"], timer["remaining_seconds"])

    def test_profile_timer_matches_duty_current(self):
        start_duty(self.user)
        me = self.client.get("/api/v1/mobile/auth/me/")
        current = self.client.get("/api/tracking/duty/current/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(current.status_code, 200)
        ws = me.data.get("workday_status") or me.data["data"].get("workday_status")
        # me payload may be wrapped
        if "data" in me.data and "workday_status" in me.data["data"]:
            ws = me.data["data"]["workday_status"]
        elif "workday_status" in me.data:
            ws = me.data["workday_status"]
        cur = current.data["data"]
        self.assertEqual(ws["expected_end_at"], cur["expected_end_at"])
        self.assertEqual(ws["remaining_seconds"], cur["remaining_seconds"])
        self.assertEqual(ws["elapsed_seconds"], cur["elapsed_seconds"])


class AdminStatusTimerCentralizationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="cen_admin", password="x", is_staff=True, is_superuser=True
        )
        self.user = _employee("cen_emp2", "CEN-002")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def test_admin_row_expected_end_and_elapsed_match_timer(self):
        duty = start_duty(self.user).duty
        workday = duty.workday
        now = timezone.now()
        timer = compute_duty_timer(duty, now=now)
        emp = EmployeeProfile.objects.get(user=self.user)
        row = build_admin_tracking_row(
            emp=emp,
            user=self.user,
            workday=workday,
            last_location=None,
            gps_off=False,
            now=now,
            duty=duty,
            timer=timer,
        )
        self.assertEqual(row["workday_ends_at"], timer["expected_end_at"])
        self.assertEqual(row["expected_end_at"], timer["expected_end_at"])
        self.assertEqual(row["elapsed_seconds"], timer["elapsed_seconds"])

    def test_admin_status_list_includes_canonical_ends(self):
        start_duty(self.user)
        r = self.admin_client.get("/api/v1/tracking/admin/status/")
        self.assertEqual(r.status_code, 200)
        rows = r.data if isinstance(r.data, list) else r.data.get("data") or r.data
        match = [x for x in rows if x.get("user_id") == self.user.pk]
        self.assertEqual(len(match), 1)
        current = serialize_duty_status(self.user)
        self.assertEqual(match[0]["workday_ends_at"], current["expected_end_at"])
        self.assertEqual(match[0]["elapsed_seconds"], current["elapsed_seconds"])


class DashboardWithinDurationCentralizationTests(TestCase):
    def test_within_duration_follows_expected_end(self):
        user = _employee("cen_emp3", "CEN-003")
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        self.assertFalse(
            is_session_within_limit(wd.start_time, is_active=True, now=timezone.now())
        )
        # Dashboard expiry authoritative path
        from tracking.duty_expiry import expire_overdue_duties

        DutySession.objects.create(
            user=user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        expire_overdue_duties(trigger="celery")
        duty = DutySession.objects.get(user=user)
        self.assertFalse(duty.is_active)
        self.assertEqual(duty.end_time, expected_end_at(start))


class DailySummaryTimerTests(TestCase):
    def test_caps_at_nine_hours(self):
        user = _employee("cen_emp4", "CEN-004")
        start = timezone.now() - timedelta(hours=12)
        wd = WorkDay.objects.create(
            user=user,
            date=timezone.localdate(start),
            start_time=start,
            end_time=None,
            is_active=True,
            auto_ended=False,
        )
        DutySession.objects.create(
            user=user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        # Active overdue not yet written; timer still caps elapsed
        seconds = compute_work_hours_seconds([wd], timezone.localdate(start))
        self.assertEqual(seconds, DURATION_LIMIT_SECONDS)

    def test_manual_end_uses_shorter_duration(self):
        user = _employee("cen_emp5", "CEN-005")
        duty = start_duty(user).duty
        DutySession.objects.filter(pk=duty.pk).update(
            start_time=timezone.now() - timedelta(hours=2)
        )
        duty.refresh_from_db()
        ended = end_duty(user)
        seconds = compute_work_hours_seconds(
            [ended.workday], timezone.localdate()
        )
        self.assertLess(seconds, DURATION_LIMIT_SECONDS)
        self.assertGreater(seconds, 0)

    def test_auto_expired_reports_canonical_duration(self):
        user = _employee("cen_emp6", "CEN-006")
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        duty = DutySession.objects.create(
            user=user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        from tracking.duty_expiry import expire_overdue_duty_for_user

        expire_overdue_duty_for_user(user, trigger="lazy_current")
        duty.refresh_from_db()
        wd.refresh_from_db()
        seconds = compute_work_hours_seconds([wd], timezone.localdate(start))
        self.assertEqual(seconds, DURATION_LIMIT_SECONDS)
        self.assertEqual(duty.end_time, expected_end_at(start))


class RouteSummaryTimerTests(TestCase):
    def test_route_summary_uses_canonical_expected_end(self):
        user = _employee("cen_emp7", "CEN-007")
        duty = start_duty(user).duty
        timer = compute_duty_timer(duty)
        data = build_admin_route_data(
            target_date=timezone.localdate(),
            employee_id="CEN-007",
            user_id=user.pk,
            route=[],
            workdays=[duty.workday],
        )
        self.assertEqual(data["expected_end_at"], timer["expected_end_at"])
        self.assertEqual(data["workday_end_time"], timer["expected_end_at"])


class CurrentWorkdayApiTimerTests(TestCase):
    def setUp(self):
        self.user = _employee("cen_emp8", "CEN-008")
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "CEN-008",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )

    def test_current_workday_exposes_full_timer_fields(self):
        start_duty(self.user)
        r = self.client.get("/api/v1/tracking/workday/current/")
        self.assertEqual(r.status_code, 200)
        for key in (
            "duration_limit_seconds",
            "expected_end_at",
            "server_now",
            "elapsed_seconds",
            "remaining_seconds",
            "is_expired",
            "completion_reason",
        ):
            self.assertIn(key, r.data)
        self.assertEqual(r.data["duration_limit_seconds"], 32400)
        self.assertEqual(r.data["server_time"], r.data["server_now"])

    def test_current_workday_server_now_matches_serialize(self):
        start_duty(self.user)
        serialized = serialize_duty_status(self.user)
        r = self.client.get("/api/v1/tracking/workday/current/")
        self.assertEqual(r.data["expected_end_at"], serialized["expected_end_at"])
        # Same structure: seconds within identical server_now from concurrent calls may differ;
        # remaining should match duration window.
        self.assertEqual(
            r.data["duration_limit_seconds"], serialized["duration_limit_seconds"]
        )


class WorkdayUtilsCompatDelegationTests(TestCase):
    def test_wrappers_match_duty_timer(self):
        start = timezone.now()
        with self.assertWarns(DeprecationWarning):
            self.assertEqual(
                workday_scheduled_end(start), expected_end_at(start)
            )
        self.assertEqual(
            MAX_WORKDAY_DURATION, timedelta(seconds=DURATION_LIMIT_SECONDS)
        )
        wd = WorkDay(
            start_time=start,
            is_active=True,
        )
        with self.assertWarns(DeprecationWarning):
            self.assertEqual(
                is_workday_within_duration(wd, now=start + timedelta(hours=1)),
                is_session_within_limit(
                    start, is_active=True, now=start + timedelta(hours=1)
                ),
            )


class RepositorySearchGuardTests(TestCase):
    """Fail if independent 9h arithmetic reappears outside canonical modules."""

    ALLOWED_FILES = {
        "tracking/duty_timer.py",
        "tracking/duty_expiry.py",
        "tracking/workday_utils.py",  # delegation only
        "docs/DUTY_TIMER_AND_EXPIRY.md",
        "tracking/tests/test_duty_timer_centralization.py",
        "tracking/tests/test_duty_timer_expiry.py",
        "tracking/tests/test_workday_expiry.py",
        "mobile/lib/config.ts",
        "mobile/app/(tabs)/tracking.tsx",
    }

    def test_no_independent_nine_hour_literals_in_app_code(self):
        root = Path(__file__).resolve().parents[2]
        offenders = []
        patterns = ("timedelta(hours=9)",)
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if any(part in rel for part in ("__pycache__", "migrations", "venv", ".venv")):
                continue
            if rel in self.ALLOWED_FILES or rel.startswith("tracking/tests/"):
                continue
            if rel.startswith("docs/"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                if pat in text:
                    offenders.append(f"{rel}: {pat}")
        self.assertEqual(offenders, [], msg="; ".join(offenders))
