"""Expire overdue DutySessions (9-hour policy). Prefer this over WorkDay-first expiry."""

from django.core.management.base import BaseCommand

from tracking.duty_expiry import expire_overdue_duties


class Command(BaseCommand):
    help = (
        "Auto-complete active DutySessions older than 9 hours "
        "(ended_at = start_time + 9h). Idempotent."
    )

    def handle(self, *args, **options):
        count = expire_overdue_duties(trigger="management_command")
        self.stdout.write(
            self.style.SUCCESS(
                f"Auto-completed {count} overdue DutySession(s)."
            )
        )
