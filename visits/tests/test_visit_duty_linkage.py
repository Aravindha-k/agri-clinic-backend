"""Visit ↔ DutySession linkage and repair_visit_duty_links."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import EmployeeProfile
from masters.models import Crop, Farmer
from tracking.day_map_service import build_duty_day_map
from tracking.duty_service import start_duty
from tracking.models import DutySession
from visits.models import Visit
from visits.services.field_visit_service import (
    link_visit_duty_session,
    resolve_duty_for_visit,
)


def _employee(username, employee_id):
    user = User.objects.create_user(username=username, password="secret123")
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000444",
        is_active_employee=True,
    )
    return user


class VisitDutyLinkageTests(TestCase):
    def setUp(self):
        self.user = _employee("visit_duty", "VD-001")
        self.other = _employee("visit_other", "VD-002")
        self.farmer = Farmer.objects.create(name="Farmer Link", phone="9888000001")
        self.crop = Crop.objects.create(name_en="Paddy", name_ta="Paddy", is_active=True)

    def _make_visit(self, employee, visit_date, **extra):
        return Visit.objects.create(
            employee=employee,
            visit_date=visit_date,
            farmer=self.farmer,
            farmer_name="Farmer Link",
            farmer_phone="9888000001",
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
            status="completed",
            **extra,
        )

    def test_new_visit_links_to_active_duty(self):
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        visit = self._make_visit(self.user, duty.date)
        linked = link_visit_duty_session(visit)
        self.assertEqual(linked.pk, duty.pk)
        visit.refresh_from_db()
        self.assertEqual(visit.duty_session_id, duty.pk)

    def test_historical_upload_links_unique_duty(self):
        past = timezone.localdate() - timedelta(days=2)
        duty = DutySession.objects.create(
            user=self.user,
            date=past,
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=2) + timedelta(hours=8),
            is_active=False,
        )
        visit = self._make_visit(self.user, past)
        linked = resolve_duty_for_visit(visit)
        self.assertEqual(linked.pk, duty.pk)

    def test_ambiguous_match_not_guessed(self):
        d = timezone.localdate() - timedelta(days=3)
        DutySession.objects.create(
            user=self.user,
            date=d,
            start_time=timezone.now() - timedelta(days=3, hours=1),
            end_time=timezone.now() - timedelta(days=3),
            is_active=False,
        )
        DutySession.objects.create(
            user=self.user,
            date=d,
            start_time=timezone.now() - timedelta(days=3, hours=5),
            end_time=timezone.now() - timedelta(days=3, hours=4),
            is_active=False,
        )
        visit = self._make_visit(self.user, d)
        visit.refresh_from_db()
        self.assertIsNone(visit.duty_session_id)
        self.assertIsNone(resolve_duty_for_visit(visit))

    def test_another_employees_duty_rejected(self):
        duty_other = start_duty(self.other, latitude=12.97, longitude=77.59).duty
        visit = self._make_visit(self.user, duty_other.date)
        visit.duty_session_id = duty_other.pk
        visit.save(update_fields=["duty_session_id"])
        resolve_duty_for_visit(visit)
        visit.refresh_from_db()
        self.assertNotEqual(visit.duty_session_id, duty_other.pk)

    def test_repair_dry_run_changes_nothing(self):
        past = timezone.localdate() - timedelta(days=1)
        duty = DutySession.objects.create(
            user=self.user,
            date=past,
            start_time=timezone.now() - timedelta(days=1),
            end_time=timezone.now() - timedelta(hours=12),
            is_active=False,
        )
        visit = self._make_visit(self.user, past)
        # Signal may auto-link deterministic matches; clear to exercise repair dry-run.
        Visit.objects.filter(pk=visit.pk).update(duty_session_id=None)
        visit.refresh_from_db()
        out = StringIO()
        call_command("repair_visit_duty_links", stdout=out)
        visit.refresh_from_db()
        self.assertIsNone(visit.duty_session_id)
        self.assertIn("proposed_deterministic: 1", out.getvalue())
        self.assertIn(str(duty.pk), out.getvalue())

    def test_repair_apply_fixes_only_deterministic(self):
        past = timezone.localdate() - timedelta(days=4)
        duty = DutySession.objects.create(
            user=self.user,
            date=past,
            start_time=timezone.now() - timedelta(days=4),
            end_time=timezone.now() - timedelta(days=3, hours=20),
            is_active=False,
        )
        amb_date = timezone.localdate() - timedelta(days=5)
        DutySession.objects.create(
            user=self.user,
            date=amb_date,
            start_time=timezone.now() - timedelta(days=5, hours=2),
            end_time=timezone.now() - timedelta(days=5),
            is_active=False,
        )
        DutySession.objects.create(
            user=self.user,
            date=amb_date,
            start_time=timezone.now() - timedelta(days=5, hours=6),
            end_time=timezone.now() - timedelta(days=5, hours=4),
            is_active=False,
        )
        v_ok = self._make_visit(self.user, past)
        v_amb = self._make_visit(self.user, amb_date)
        Visit.objects.filter(pk__in=[v_ok.pk, v_amb.pk]).update(duty_session_id=None)
        call_command("repair_visit_duty_links", "--apply", stdout=StringIO())
        v_ok.refresh_from_db()
        v_amb.refresh_from_db()
        self.assertEqual(v_ok.duty_session_id, duty.pk)
        self.assertIsNone(v_amb.duty_session_id)

    def test_repaired_visit_appears_once_on_day_map(self):
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        visit = self._make_visit(self.user, duty.date)
        link_visit_duty_session(visit)
        day_map = build_duty_day_map(duty, viewer=self.user)
        self.assertGreaterEqual(day_map.get("summary", {}).get("visit_count", 0), 1)
        visit_ids = [
            v.get("visit_id") or v.get("id")
            for v in (day_map.get("visits") or [])
        ]
        if visit_ids:
            self.assertEqual(visit_ids.count(visit.pk), 1)
