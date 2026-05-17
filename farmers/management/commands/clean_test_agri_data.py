from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from farmers.data_audit import (
    build_agri_audit_report,
    cleanup_visits_qs,
    farmers_safe_to_delete,
    is_clearly_test_farmer,
    test_farmers_qs,
)
from visits.submitted import get_visit_cleanup_counts


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
        "Remove test/demo farmers and incomplete/orphan/draft visits. "
        "Dry-run by default; pass --confirm to delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview only (default when --confirm is not passed).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Apply deletions.",
        )

    def handle(self, *args, **options):
        dry_run = not options["confirm"]

        report = build_agri_audit_report()
        visit_qs = cleanup_visits_qs()
        visit_count = visit_qs.count()
        safe_farmers, skipped_farmers = farmers_safe_to_delete()

        self.stdout.write(self.style.MIGRATE_HEADING("Agri Clinic test data cleanup"))
        self.stdout.write("")
        self.stdout.write("Before:")
        self._print_snapshot(report)

        self.stdout.write("")
        self.stdout.write(f"Visits to delete: {visit_count}")
        for v in visit_qs.order_by("-id")[:15]:
            self.stdout.write(
                f"  visit id={v.id} status={v.status!r} farmer_id={v.farmer_id} "
                f"crop_id={v.crop_id} lat={v.latitude} lng={v.longitude}"
            )
        if visit_count > 15:
            self.stdout.write(f"  ... and {visit_count - 15} more")

        self.stdout.write("")
        self.stdout.write(f"Test farmers to delete: {len(safe_farmers)}")
        for f in safe_farmers[:15]:
            self.stdout.write(f"  farmer id={f.id} name={f.name!r} phone={f.phone!r}")
        if len(safe_farmers) > 15:
            self.stdout.write(f"  ... and {len(safe_farmers) - 15} more")

        if skipped_farmers:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {len(skipped_farmers)} test-pattern farmer(s) (not clearly safe):"
                )
            )
            for farmer, reason in skipped_farmers[:10]:
                self.stdout.write(f"  id={farmer.id} {farmer.name!r}: {reason}")

        ambiguous = [
            f
            for f in test_farmers_qs()
            if not is_clearly_test_farmer(f) and f not in safe_farmers
        ]
        if ambiguous:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(ambiguous)} farmer(s) match test patterns but were not selected "
                    "(review manually before delete)."
                )
            )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run: no rows deleted. Re-run with --confirm to apply."
                )
            )
            return

        if visit_count == 0 and not safe_farmers:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        with transaction.atomic():
            deleted_visits, visit_detail = visit_qs.delete()
            farmer_ids = [f.pk for f in safe_farmers]
            from masters.models import Farmer

            deleted_farmers, farmer_detail = (
                Farmer.objects.filter(pk__in=farmer_ids).delete()
                if farmer_ids
                else (0, {})
            )

        _invalidate_caches()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_visits} visit-related row(s): {visit_detail}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_farmers} farmer-related row(s): {farmer_detail}"
            )
        )
        self.stdout.write("")
        self.stdout.write("After:")
        self._print_snapshot(build_agri_audit_report())

    def _print_snapshot(self, report: dict) -> None:
        f = report["farmers"]
        v = report["visits"]
        self.stdout.write(f"  active farmers:    {f['active']}")
        self.stdout.write(f"  submitted visits: {v['submitted_visits']}")
        self.stdout.write(f"  total visits:      {v['total_visits']}")
        self.stdout.write(f"  incomplete:        {v['incomplete_visits']}")
