from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature

from accounts.models import EmployeeProfile
from tracking.duty_service import end_duty, start_duty
from tracking.models import DutySession, WorkDay


class DutyConcurrencyPostgresTest(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row-lock semantics required")
        self.user = User.objects.create_user(username="duty_race", password="x")
        EmployeeProfile.objects.create(
            user=self.user,
            employee_id="RACE-001",
            phone="9000000999",
            is_active_employee=True,
        )

    def _run_concurrently(self, operation):
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                return operation(user)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            return [future.result(timeout=15) for future in futures]

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_start_reuses_single_active_session(self):
        results = self._run_concurrently(
            lambda user: start_duty(user, latitude=12.9716, longitude=77.5946)
        )
        duties = [result.duty for result in results]

        self.assertEqual({duty.pk for duty in duties}, {duties[0].pk})
        self.assertEqual([result.created for result in results].count(True), 1)
        self.assertEqual([result.created for result in results].count(False), 1)
        self.assertEqual(
            {duty.start_time for duty in duties},
            {duties[0].start_time},
        )
        self.assertEqual(
            DutySession.objects.filter(user=self.user).count(),
            1,
        )
        self.assertEqual(
            WorkDay.objects.filter(user=self.user).count(),
            1,
        )
        self.assertEqual(duties[0].start_time, duties[0].workday.start_time)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_end_is_idempotent(self):
        started = start_duty(
            self.user,
            latitude=12.9716,
            longitude=77.5946,
        ).duty

        duties = self._run_concurrently(end_duty)

        self.assertEqual({duty.pk for duty in duties}, {started.pk})
        self.assertEqual({duty.end_time for duty in duties}, {duties[0].end_time})
        ended = DutySession.objects.get(pk=started.pk)
        self.assertFalse(ended.is_active)
        self.assertIsNotNone(ended.end_time)
        self.assertFalse(WorkDay.objects.get(pk=started.workday_id).is_active)
