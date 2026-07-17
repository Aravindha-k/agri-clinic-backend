"""PostgreSQL-only regression tests for concurrent worker connection leaks."""

from __future__ import annotations

import time

from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from config.pg_test_diagnostics import count_test_db_sessions, resolve_test_database_name
from tracking.duty_service import end_duty, start_duty
from tracking.duty_expiry import expire_overdue_duties
from utils.concurrency_test_helpers import run_concurrent_workers, run_two_concurrent


class PostgresConnectionLeakRegressionTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required")
        self.user = User.objects.create_user(username="leak_user", password="x")
        self.test_db_name = resolve_test_database_name()

    def _assert_no_extra_sessions(self, *, label: str):
        connections.close_all()
        time.sleep(0.1)
        connections.close_all()
        count = count_test_db_sessions(self.test_db_name)
        self.assertEqual(
            count,
            0,
            f"{label}: expected 0 sessions on {self.test_db_name}, found {count}",
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_start_end_do_not_leak_sessions(self):
        run_concurrent_workers(
            lambda: start_duty(self.user, latitude=12.97, longitude=77.59)
        )
        self._assert_no_extra_sessions(label="concurrent_start")

        run_concurrent_workers(lambda: end_duty(self.user))
        self._assert_no_extra_sessions(label="concurrent_end")

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_expiry_workers_do_not_leak_sessions(self):
        from datetime import timedelta

        from django.utils import timezone

        from tracking.models import DutySession, WorkDay

        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        run_concurrent_workers(lambda: expire_overdue_duties(trigger="celery"))
        self._assert_no_extra_sessions(label="concurrent_expiry")

    @skipUnlessDBFeature("has_select_for_update")
    def test_run_two_concurrent_does_not_leak_sessions(self):
        from datetime import timedelta

        from django.utils import timezone

        from tracking.duty_expiry import expire_overdue_duty_for_user
        from tracking.models import DutySession, WorkDay

        start = timezone.now() - timedelta(hours=10)
        wd = WorkDay.objects.create(
            user=self.user,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )
        DutySession.objects.create(
            user=self.user,
            workday=wd,
            date=timezone.localdate(start),
            start_time=start,
            is_active=True,
        )

        run_two_concurrent(
            lambda: expire_overdue_duty_for_user(self.user, trigger="celery"),
            lambda: end_duty(self.user),
        )
        self._assert_no_extra_sessions(label="run_two_concurrent")
