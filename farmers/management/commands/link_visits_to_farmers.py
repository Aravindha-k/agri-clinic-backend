"""
Link orphan visits to existing Farmer rows only (never creates farmers).

Matching order:
  1. farmer_phone exact (single match)
  2. farmer_name + village_id (single match)
  3. farmer_name case-insensitive (single match only)

Ambiguous or no match: reported for manual fix.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from farmers.audit import _match_farmer_for_visit
from visits.models import Visit


class Command(BaseCommand):
    help = "Backfill Visit.farmer FK from existing Farmer records (no new farmers)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write farmer_id to matched visits (default is preview only).",
        )

    def handle(self, *args, **options):
        dry_run = not options["apply"]

        orphans = Visit.objects.filter(farmer_id__isnull=True).order_by("id")
        total = orphans.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No orphan visits."))
            return

        linked = 0
        ambiguous = 0
        unmatched = 0
        updates = []

        for visit in orphans.iterator(chunk_size=200):
            farmer, reason = _match_farmer_for_visit(visit)
            if farmer:
                linked += 1
                updates.append((visit.pk, farmer.pk, reason))
            elif reason.endswith("_ambiguous"):
                ambiguous += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  AMBIGUOUS visit {visit.pk}: {visit.farmer_name} / {visit.farmer_phone} ({reason})"
                    )
                )
            else:
                unmatched += 1
                self.stdout.write(
                    f"  NO MATCH visit {visit.pk}: {visit.farmer_name} / {visit.farmer_phone}"
                )

        self.stdout.write(
            f"\nOrphans: {total} | linkable: {linked} | ambiguous: {ambiguous} | no match: {unmatched}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written. Use --apply to save."))
            return

        if not updates:
            self.stdout.write(self.style.WARNING("Nothing to apply."))
            return

        with transaction.atomic():
            for visit_id, farmer_id, reason in updates:
                Visit.objects.filter(pk=visit_id, farmer_id__isnull=True).update(
                    farmer_id=farmer_id
                )
                self.stdout.write(f"  Linked visit {visit_id} -> farmer {farmer_id} ({reason})")

        remaining = Visit.objects.filter(farmer_id__isnull=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Applied {len(updates)} links. Orphans remaining: {remaining}"
            )
        )
