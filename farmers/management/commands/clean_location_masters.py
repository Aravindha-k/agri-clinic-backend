"""
Prune district/village masters to only locations referenced by farmer records.

Usage:
  python manage.py clean_location_masters --dry-run
  python manage.py clean_location_masters --confirm
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from farmers.farmer_cleanup import create_db_backup
from farmers.location_cleanup import (
    build_location_cleanup_plan,
    execute_location_cleanup,
    farmer_location_summary,
    verify_farmer_locations,
)


class Command(BaseCommand):
    help = (
        "Remove district/village master rows not referenced by any farmer. "
        "Creates a DB backup before deletion when --confirm is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show plan only (default when --confirm is not passed).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Backup DB and delete orphan location masters.",
        )
        parser.add_argument(
            "--backup-dir",
            default="",
            help="Backup directory (default: <project>/backups).",
        )
        parser.add_argument(
            "--show-limit",
            type=int,
            default=25,
            help="Max orphan names to print per category (default 25).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or not options["confirm"]
        if options["dry_run"] and options["confirm"]:
            raise CommandError("Use either --dry-run or --confirm, not both.")

        show_limit = max(0, int(options["show_limit"]))
        summary = farmer_location_summary()
        plan = build_location_cleanup_plan()

        self.stdout.write(self.style.MIGRATE_HEADING("Farmer location usage"))
        self.stdout.write(f"  Farmers: {summary['farmer_count']}")
        self.stdout.write(
            f"  Districts used by farmers: {summary['districts_used_count']}"
        )
        self.stdout.write(
            f"  Villages used by farmers: {summary['villages_used_count']}"
        )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Location master audit"))
        self.stdout.write(f"  Total districts (before): {plan.total_districts}")
        self.stdout.write(f"  Total villages (before): {plan.total_villages}")
        self.stdout.write(
            f"  Districts to keep: {len(plan.districts_to_keep)} | "
            f"to remove: {len(plan.districts_to_remove)}"
        )
        self.stdout.write(
            f"  Villages to keep: {len(plan.villages_to_keep)} | "
            f"to remove: {len(plan.villages_to_remove)}"
        )

        if plan.farmers_without_village:
            self.stdout.write(
                self.style.WARNING(
                    f"  Farmers without village_id: {plan.farmers_without_village}"
                )
            )
        if plan.farmers_without_district:
            self.stdout.write(
                self.style.WARNING(
                    f"  Farmers without district_id: {plan.farmers_without_district}"
                )
            )
        if plan.villages_without_district:
            self.stdout.write(
                self.style.WARNING(
                    f"  Kept villages missing district_id: {plan.villages_without_district}"
                )
            )

        self._print_orphan_sample("Villages to remove", plan.villages_to_remove, show_limit)
        self._print_orphan_sample(
            "Districts to remove", plan.districts_to_remove, show_limit
        )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("Dry-run only — no backup or deletion applied.")
            )
            self.stdout.write(json.dumps(plan.to_dict(), indent=2, default=str))
            return

        if not plan.villages_to_remove and not plan.districts_to_remove:
            self.stdout.write(self.style.SUCCESS("Nothing to remove."))
            self._print_verification()
            return

        backup_dir = (
            Path(options["backup_dir"])
            if options["backup_dir"]
            else Path(settings.BASE_DIR) / "backups"
        )
        backup_path = create_db_backup(backup_dir)
        if not backup_path.exists() or backup_path.stat().st_size == 0:
            raise CommandError(f"Backup failed or empty: {backup_path}")
        self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_path}"))

        deleted = execute_location_cleanup(plan)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Deleted: {deleted}"))

        self._print_verification()
        report = verify_farmer_locations()
        report["backup_path"] = str(backup_path)
        report["deleted"] = deleted
        self.stdout.write(json.dumps(report, indent=2, default=str))

    def _print_orphan_sample(self, label: str, rows: list, limit: int) -> None:
        if not rows:
            return
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"{label} ({len(rows)}):"))
        for row in rows[:limit]:
            self.stdout.write(f"  id={row['id']} name={row['name']!r}")
        if len(rows) > limit:
            self.stdout.write(f"  ... and {len(rows) - limit} more")

    def _print_verification(self) -> None:
        report = verify_farmer_locations()
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Verification"))
        self.stdout.write(f"  Farmer count: {report['farmer_count']}")
        self.stdout.write(f"  District count: {report['district_count']}")
        self.stdout.write(f"  Village count: {report['village_count']}")
        self.stdout.write(
            f"  Farmers missing village: {report['farmers_missing_village']}"
        )
        self.stdout.write(
            f"  Farmers missing district: {report['farmers_missing_district']}"
        )
        self.stdout.write(
            f"  Farmer villages missing district: {report['farmer_villages_missing_district']}"
        )
        if report["ok"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "  All farmers have valid village/district references."
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR("  Location integrity check failed — review report.")
            )
