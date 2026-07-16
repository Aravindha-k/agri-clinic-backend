"""Dry-run repair of Visit ↔ DutySession links."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from tracking.models import DutySession
from visits.models import Visit
from visits.submitted import submitted_visits_qs


def propose_duty_for_visit(visit: Visit) -> tuple[DutySession | None, str]:
    """
    Return (duty, reason) for repair proposals.
    Only returns a duty when the match is deterministic (exactly one).
    """
    if not visit.employee_id or not visit.visit_date:
        return None, "missing_employee_or_date"

    active = (
        DutySession.objects.filter(
            user_id=visit.employee_id,
            is_active=True,
            date=visit.visit_date,
        )
        .order_by("-start_time")
        .first()
    )
    if active:
        return active, "active_same_date"

    matches = list(
        DutySession.objects.filter(
            user_id=visit.employee_id, date=visit.visit_date
        ).order_by("-start_time")
    )
    if len(matches) == 1:
        return matches[0], "unique_historical"
    if len(matches) == 0:
        return None, "no_match"
    return None, f"ambiguous:{len(matches)}"


class Command(BaseCommand):
    help = (
        "Propose/repair Visit.duty_session links. Dry-run by default; "
        "--apply only updates deterministic one-to-one matches."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply deterministic repairs only.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        unmatched = list(
            submitted_visits_qs()
            .filter(duty_session_id__isnull=True)
            .only("id", "employee_id", "visit_date", "duty_session_id")
            .order_by("id")
        )
        proposed = 0
        ambiguous = 0
        no_match = 0
        applied = 0

        self.stdout.write("=== repair_visit_duty_links ===")
        self.stdout.write(f"unmatched_submitted_visits: {len(unmatched)}")

        for visit in unmatched:
            duty, reason = propose_duty_for_visit(visit)
            if duty is None:
                if reason.startswith("ambiguous"):
                    ambiguous += 1
                else:
                    no_match += 1
                self.stdout.write(
                    f"  visit_id={visit.pk} employee={visit.employee_id} "
                    f"date={visit.visit_date} -> SKIP ({reason})"
                )
                continue
            proposed += 1
            self.stdout.write(
                f"  visit_id={visit.pk} employee={visit.employee_id} "
                f"date={visit.visit_date} -> duty_id={duty.pk} ({reason})"
            )
            if apply:
                Visit.objects.filter(pk=visit.pk, duty_session_id__isnull=True).update(
                    duty_session_id=duty.pk
                )
                applied += 1

        self.stdout.write(f"proposed_deterministic: {proposed}")
        self.stdout.write(f"ambiguous: {ambiguous}")
        self.stdout.write(f"no_match: {no_match}")
        self.stdout.write(f"applied: {applied if apply else 0}")
        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to repair.")
            )
