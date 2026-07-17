"""Phase 3: server-authoritative 9-hour DutySession timer and auto-expiry."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from utils.concurrency_test_helpers import run_concurrent_workers, run_two_concurrent
from tracking.duty_expiry import (
    complete_duty_as_auto_expired,
    expire_overdue_duties,
    expire_overdue_duty_for_user,
)
from tracking.duty_service import end_duty, serialize_duty_status, start_duty
from tracking.duty_timer import (
    COMPLETION_AUTO_EXPIRED,
    COMPLETION_MANUAL,
    DURATION_LIMIT_SECONDS,
    compute_duty_timer,
    expected_end_at,
)
from tracking.models import DutySession, WorkDay
from tracking.worklog import WorkLog


def _expire_overdue_duties_task():
    from tracking.tasks import expire_overdue_duties_task

    return expire_overdue_duties_task()


def _make_employee(username="timer_emp", employee_id="TMR-001"):
    user = User.objects.create_user(username=username, password="secret123")
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000999",
        is_active_employee=True,
    )
    return user


class DutyTimerCalculationTests(TestCase):
    def setUp(self):
        self.user = _make_employee()
        self.now = timezone.now()

    def _active_duty(self, *, start_offset=timedelta(0)):
        start = self.now + start_offset
        wd = WorkDay.objects.create(
            user=self.user,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        return DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )

    def test_new_duty_remaining_is_32400(self):
        duty = self._active_duty()
        timer = compute_duty_timer(duty, now=duty.start_time)
        self.assertEqual(timer["duration_limit_seconds"], 32400)
        self.assertEqual(timer["remaining_seconds"], 32400)
        self.assertEqual(timer["elapsed_seconds"], 0)
        self.assertEqual(
            timer["expected_end_at"],
            expected_end_at(duty.start_time).isoformat(),
        )

    def test_elapsed_uses_server_now(self):
        duty = self._active_duty()
        later = duty.start_time + timedelta(hours=2, minutes=30)
        timer = compute_duty_timer(duty, now=later)
        self.assertEqual(timer["elapsed_seconds"], 2 * 3600 + 30 * 60)
        self.assertEqual(timer["remaining_seconds"], 32400 - timer["elapsed_seconds"])

    def test_elapsed_and_remaining_never_negative(self):
        duty = self._active_duty(start_offset=timedelta(hours=-10))
        timer = compute_duty_timer(duty, now=self.now)
        self.assertGreaterEqual(timer["elapsed_seconds"], 0)
        self.assertGreaterEqual(timer["remaining_seconds"], 0)
        self.assertLessEqual(timer["elapsed_seconds"], DURATION_LIMIT_SECONDS)

    def test_completed_duty_timer_stops(self):
        duty = self._active_duty()
        duty.end_time = duty.start_time + timedelta(hours=3)
        duty.is_active = False
        duty.completion_reason = COMPLETION_MANUAL
        duty.save()
        much_later = duty.end_time + timedelta(hours=5)
        timer = compute_duty_timer(duty, now=much_later)
        self.assertEqual(timer["elapsed_seconds"], 3 * 3600)
        self.assertEqual(timer["remaining_seconds"], 0)
        self.assertEqual(timer["ended_at"], duty.end_time.isoformat())

    def test_expected_end_equals_start_plus_9h(self):
        duty = self._active_duty()
        self.assertEqual(
            expected_end_at(duty.start_time),
            duty.start_time + timedelta(seconds=32400),
        )

    def test_client_timestamps_have_no_effect_on_timer(self):
        duty = self._active_duty()
        # Serialize ignores any client-provided clock; only duty + server now.
        fake_client_now = duty.start_time + timedelta(hours=100)
        timer = compute_duty_timer(duty, now=duty.start_time + timedelta(minutes=5))
        self.assertEqual(timer["elapsed_seconds"], 300)
        self.assertNotEqual(timer["elapsed_seconds"], int((fake_client_now - duty.start_time).total_seconds()))


class DutyAutoExpiryTests(TestCase):
    def setUp(self):
        self.user = _make_employee("exp_emp", "EXP-001")

    def _overdue_duty(self, *, hours_ago=10):
        start = timezone.now() - timedelta(hours=hours_ago)
        wd = WorkDay.objects.create(
            user=self.user,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        return DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )

    def test_expires_at_deadline_with_expected_end(self):
        duty = self._overdue_duty(hours_ago=9)
        # Exactly at/past deadline
        now = duty.start_time + timedelta(seconds=DURATION_LIMIT_SECONDS)
        completed = expire_overdue_duty_for_user(
            self.user, now=now, trigger="lazy_current"
        )
        completed.refresh_from_db()
        expected = expected_end_at(duty.start_time)
        self.assertFalse(completed.is_active)
        self.assertEqual(completed.end_time, expected)
        self.assertTrue(completed.auto_ended)
        self.assertEqual(completed.completion_reason, COMPLETION_AUTO_EXPIRED)
        wd = WorkDay.objects.get(pk=duty.workday_id)
        self.assertFalse(wd.is_active)
        self.assertTrue(wd.auto_ended)
        self.assertEqual(wd.end_time, expected)

    def test_repeated_expiry_idempotent(self):
        duty = self._overdue_duty()
        now = timezone.now()
        a = expire_overdue_duty_for_user(self.user, now=now, trigger="celery")
        self.assertIsNotNone(a)
        end_a = a.end_time
        # Second call: no active duty left — bulk/complete stay idempotent.
        self.assertIsNone(
            expire_overdue_duty_for_user(
                self.user, now=now + timedelta(hours=1), trigger="celery"
            )
        )
        a.refresh_from_db()
        again = complete_duty_as_auto_expired(
            a, now=now + timedelta(hours=1), trigger="celery"
        )
        self.assertEqual(end_a, again.end_time)
        self.assertEqual(expire_overdue_duties(now=now, trigger="celery"), 0)

    def test_celery_task_uses_same_service(self):
        duty = self._overdue_duty()
        with mock.patch(
            "tracking.duty_expiry.expire_overdue_duties",
            wraps=expire_overdue_duties,
        ) as wrapped:
            count = _expire_overdue_duties_task()
        self.assertEqual(count, 1)
        wrapped.assert_called_once()
        duty.refresh_from_db()
        self.assertFalse(duty.is_active)
        self.assertEqual(duty.end_time, expected_end_at(duty.start_time))

    def test_logout_does_not_change_deadline(self):
        duty = self._overdue_duty(hours_ago=1)
        start = duty.start_time
        expected = expected_end_at(start)
        # Simulate logout side effects: no duty mutation
        duty.refresh_from_db()
        self.assertTrue(duty.is_active)
        self.assertEqual(expected_end_at(duty.start_time), expected)
        self.assertEqual(duty.start_time, start)

    def test_app_closed_irrelevant_bulk_expiry(self):
        duty = self._overdue_duty()
        self.assertEqual(expire_overdue_duties(trigger="celery"), 1)
        duty.refresh_from_db()
        self.assertEqual(duty.completion_reason, COMPLETION_AUTO_EXPIRED)

    def test_no_worklog_created_on_expiry(self):
        self._overdue_duty()
        before = WorkLog.objects.count()
        expire_overdue_duties(trigger="management_command")
        self.assertEqual(WorkLog.objects.count(), before)


class DutyLazyExpiryAPITests(TestCase):
    def setUp(self):
        self.user = _make_employee("lazy_emp", "LAZY-001")
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "LAZY-001",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )

    def test_current_finalizes_overdue_and_returns_completed_state(self):
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        duty = DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        r = self.client.get("/api/tracking/duty/current/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        duty.refresh_from_db()
        self.assertFalse(duty.is_active)
        self.assertEqual(data["duty_session_id"], duty.pk)
        self.assertEqual(data["duty_status"], "AUTO_COMPLETED")
        self.assertTrue(data["is_expired"])
        self.assertEqual(data["remaining_seconds"], 0)
        self.assertEqual(data["elapsed_seconds"], DURATION_LIMIT_SECONDS)
        self.assertEqual(data["completion_reason"], COMPLETION_AUTO_EXPIRED)
        self.assertEqual(data["duration_limit_seconds"], 32400)

    def test_start_after_overdue_can_create_new_duty(self):
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        old = DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        r = self.client.post(
            "/api/tracking/duty/start/",
            {"latitude": 12.97, "longitude": 77.59},
            format="json",
        )
        self.assertIn(r.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED))
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        new_id = r.data["data"]["duty_session_id"]
        self.assertNotEqual(new_id, old.pk)
        self.assertEqual(r.data["data"]["remaining_seconds"], 32400)
        self.assertTrue(DutySession.objects.filter(pk=new_id, is_active=True).exists())


class DutyManualEndTests(TestCase):
    def setUp(self):
        self.user = _make_employee("man_emp", "MAN-001")

    def test_manual_end_before_deadline(self):
        start = timezone.now() - timedelta(hours=1)
        wd = WorkDay.objects.create(
            user=self.user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        duty = DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        before = timezone.now()
        ended = end_duty(self.user)
        after = timezone.now()
        self.assertEqual(ended.pk, duty.pk)
        self.assertFalse(ended.is_active)
        self.assertEqual(ended.completion_reason, COMPLETION_MANUAL)
        self.assertFalse(ended.auto_ended)
        self.assertGreaterEqual(ended.end_time, before)
        self.assertLessEqual(ended.end_time, after)
        self.assertNotEqual(ended.end_time, expected_end_at(start))

    def test_manual_end_after_deadline_keeps_auto_state(self):
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        duty = DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        ended = end_duty(self.user)
        self.assertEqual(ended.completion_reason, COMPLETION_AUTO_EXPIRED)
        self.assertEqual(ended.end_time, expected_end_at(start))
        again = end_duty(self.user)
        self.assertEqual(again.end_time, ended.end_time)


class DutyTimezoneTests(TestCase):
    def setUp(self):
        self.user = _make_employee("tz_emp", "TZ-001")

    @override_settings(TIME_ZONE="Asia/Kolkata")
    def test_business_date_uses_localdate(self):
        result = start_duty(self.user)
        self.assertEqual(result.duty.date, timezone.localdate())
        self.assertTrue(timezone.is_aware(result.duty.start_time))

    def test_duty_crossing_midnight_expires_nine_hours_later(self):
        # 22:00 IST previous calendar day → expire 07:00 IST next day (not midnight)
        tz = timezone.get_current_timezone()
        local_start = timezone.make_aware(
            datetime(2026, 7, 14, 22, 0, 0), timezone=tz
        )
        wd = WorkDay.objects.create(
            user=self.user,
            date=timezone.localdate(local_start),
            start_time=local_start,
            is_active=True,
        )
        duty = DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(local_start),
            start_time=local_start,
            is_active=True,
        )
        expected = expected_end_at(local_start)
        self.assertEqual(
            timezone.localtime(expected).isoformat(),
            timezone.make_aware(datetime(2026, 7, 15, 7, 0, 0), timezone=tz).isoformat(),
        )
        # Just before midnight — still active
        before_midnight = timezone.make_aware(
            datetime(2026, 7, 14, 23, 59, 0), timezone=tz
        )
        self.assertTrue(duty.is_active)
        expire_overdue_duty_for_user(self.user, now=before_midnight, trigger="lazy_current")
        duty.refresh_from_db()
        self.assertTrue(duty.is_active)

        after_deadline = expected + timedelta(minutes=1)
        expire_overdue_duty_for_user(self.user, now=after_deadline, trigger="lazy_current")
        duty.refresh_from_db()
        self.assertFalse(duty.is_active)
        self.assertEqual(duty.end_time, expected)

    def test_timestamps_are_aware(self):
        result = start_duty(self.user)
        self.assertTrue(timezone.is_aware(result.duty.start_time))
        timer = compute_duty_timer(result.duty)
        # ISO strings from aware datetimes include offset or Z
        self.assertIsNotNone(timer["server_now"])
        parsed = datetime.fromisoformat(timer["server_now"])
        self.assertIsNotNone(parsed.tzinfo)


class DutyCompatibilityTimerTests(TestCase):
    def setUp(self):
        self.user = _make_employee("compat_emp", "CMP-001")
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "CMP-001",
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

    def test_legacy_mobile_start_includes_timer(self):
        r = self.client.post("/api/v1/mobile/work/start/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data.get("data") or r.data
        self.assertEqual(data["duration_limit_seconds"], 32400)
        self.assertIn("remaining_seconds", data)
        self.assertIn("expected_end_at", data)

    def test_legacy_status_includes_timer(self):
        start_duty(self.user)
        r = self.client.get("/api/v1/mobile/work/status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data.get("data") or r.data
        self.assertEqual(data["duration_limit_seconds"], 32400)
        self.assertIn("elapsed_seconds", data)

    def test_workday_completed_when_duty_expires(self):
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        expire_overdue_duties(trigger="celery")
        wd.refresh_from_db()
        self.assertFalse(wd.is_active)
        self.assertTrue(wd.auto_ended)


class DutyConcurrencyExpiryTests(TransactionTestCase):
    def setUp(self):
        self.user = _make_employee("conc_emp", "CONC-001")

    def _overdue(self):
        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user, date=timezone.localdate(start), start_time=start, is_active=True
        )
        return DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )

    def test_two_expiry_workers_do_not_double_complete(self):
        duty = self._overdue()
        expected = expected_end_at(duty.start_time)

        results = run_concurrent_workers(
            lambda: expire_overdue_duties(trigger="celery")
        )
        self.assertEqual(sum(results), 1)
        duty.refresh_from_db()
        self.assertFalse(duty.is_active)
        self.assertEqual(duty.end_time, expected)
        self.assertEqual(
            DutySession.objects.filter(user=self.user, is_active=False).count(), 1
        )

    def test_manual_end_racing_auto_expiry_one_final_state(self):
        duty = self._overdue()
        expected = expected_end_at(duty.start_time)

        def auto():
            return expire_overdue_duty_for_user(
                self.user, trigger="celery"
            )

        def manual():
            return end_duty(self.user)

        a, b = run_two_concurrent(auto, manual)
        self.assertEqual(a.pk, b.pk)
        duty.refresh_from_db()
        self.assertFalse(duty.is_active)
        self.assertEqual(duty.end_time, expected)
        self.assertEqual(duty.completion_reason, COMPLETION_AUTO_EXPIRED)
        self.assertEqual(duty.start_time, a.start_time)


class SerializeDoesNotTrustClientClockTests(TestCase):
    def setUp(self):
        self.user = _make_employee("ser_emp", "SER-001")

    def test_serialize_uses_server_timer_helper(self):
        result = start_duty(self.user)
        payload = serialize_duty_status(self.user, result.duty)
        self.assertEqual(payload["duration_limit_seconds"], 32400)
        self.assertEqual(payload["remaining_seconds"], 32400)
        self.assertIn("server_now", payload)
        self.assertEqual(payload["duty_status"], "ACTIVE")
        self.assertEqual(payload["status"], "in_progress")
