import json

from django.core.management.base import BaseCommand

from farmers.audit import build_farmer_visit_audit


class Command(BaseCommand):
    help = "Print farmer vs visit integrity audit (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output full JSON report.",
        )

    def handle(self, *args, **options):
        report = build_farmer_visit_audit()
        counts = report["counts"]
        integrity = report["integrity"]

        self.stdout.write("=== Farmer / Visit audit ===")
        for key, val in counts.items():
            self.stdout.write(f"  {key}: {val}")

        self.stdout.write("\n=== Farmers list / dashboard (expected) ===")
        self.stdout.write(
            f"  GET /api/v1/farmers/ count: {counts['total_farmers_all']} (all master records)"
        )
        self.stdout.write(
            f"  dashboard total_farmers: {counts['total_farmers_all']} (same queryset)"
        )

        self.stdout.write("\n=== Integrity ===")
        for key, val in integrity.items():
            self.stdout.write(f"  {key}: {val}")

        orphans = report["visits_without_farmer_fk"]
        if orphans:
            self.stdout.write(f"\n=== Orphan visits (sample {len(orphans)}) ===")
            for row in orphans[:15]:
                match = row.get("suggested_match")
                mid = match["id"] if match else "-"
                self.stdout.write(
                    f"  visit {row['visit_id']}: {row['farmer_name']} / {row['farmer_phone']} "
                    f"-> match {mid} ({row['match_reason']})"
                )

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))

        if counts["visits_without_farmer_fk"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nRun: python manage.py link_visits_to_farmers  (preview)"
                    "\n     python manage.py link_visits_to_farmers --apply  (link existing farmers only)"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nAll visits have farmer FK."))
