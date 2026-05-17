from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from visits.submitted import get_visit_cleanup_counts, incomplete_visits_qs


def _invalidate_caches() -> None:
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception:
        pass
    try:
        from farmers.services import invalidate_farmers_list_cache

        invalidate_farmers_list_cache()
    except Exception:
        pass


class Command(BaseCommand):
    help = (
        "Remove legacy incomplete visits (no farmer, crop, or GPS). "
        "Dry-run by default; pass --confirm to delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Delete incomplete visits (default is dry-run only).",
        )

    def handle(self, *args, **options):
        counts = get_visit_cleanup_counts()
        self._print_counts(counts)

        delete_count = counts["incomplete_visits"]

        if not options["confirm"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run: would delete {delete_count} incomplete visit(s). "
                    "Re-run with --confirm to apply."
                )
            )
            return

        if delete_count == 0:
            self.stdout.write(self.style.SUCCESS("No incomplete visits to delete."))
            return

        with transaction.atomic():
            deleted, per_model = incomplete_visits_qs().delete()

        _invalidate_caches()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} row(s) across related tables: {per_model}"
            )
        )
        after = get_visit_cleanup_counts()
        self.stdout.write("After cleanup:")
        self._print_counts(after)

    def _print_counts(self, counts: dict[str, int]) -> None:
        self.stdout.write("Visit cleanup summary:")
        self.stdout.write(f"  total visits:      {counts['total_visits']}")
        self.stdout.write(f"  submitted visits:  {counts['submitted_visits']}")
        self.stdout.write(f"  incomplete visits: {counts['incomplete_visits']}")
        self.stdout.write(f"  no farmer:         {counts['no_farmer']}")
        self.stdout.write(f"  missing crop:      {counts['missing_crop']}")
        self.stdout.write(f"  missing GPS:       {counts['missing_gps']}")
        self.stdout.write("\nSubmitted by employee:")
        for row in counts.get("submitted_by_employee") or []:
            self.stdout.write(
                f"  {row['employee_username'] or row['employee_id']}: {row['visit_count']}"
            )
