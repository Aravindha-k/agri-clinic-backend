"""
Merge-import farmers from additional quarter Excel files (Q3/Q4) into live data.

Does not delete existing farmers, visits, or tracking data.

Usage:
  python manage.py import_farmers_quarters --merge --dry-run
  python manage.py import_farmers_quarters --merge --confirm \\
      --quarter3 "imports/QUARTER 3GrpSum.xlsx" \\
      --quarter4 "imports/QUARTER 4GrpSum.xlsx"
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q

from farmers.db_debug import get_database_connection_info, resolve_quarter_path
from farmers.farmer_cleanup import create_db_backup
from farmers.farmer_quarter_import import (
    preview_merge_import,
    preview_quarter_file,
    run_merge_import,
)
from farmers.management.commands.clean_and_import_farmers import (
    _invalidate_caches,
    _print_db_context,
    _verify_apis,
)
from masters.models import Farmer, Village

DEFAULT_QUARTER3_PATH = "imports/QUARTER 3GrpSum.xlsx"
DEFAULT_QUARTER4_PATH = "imports/QUARTER 4GrpSum.xlsx"


def _require_excel_files(*paths: Path) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise CommandError(
            "Excel file(s) missing — place files under imports/ and retry:\n  "
            + "\n  ".join(missing)
        )


def _recent_merge_farmers(limit: int = 20) -> list[dict]:
    return list(
        Farmer.objects.select_related("village", "district")
        .filter(
            Q(source_quarter__icontains="quarter3")
            | Q(source_quarter__icontains="quarter4")
        )
        .order_by("-id")
        .values(
            "id",
            "name",
            "phone",
            "source_quarter",
            "source_file",
            "state",
            village_name=F("village__name"),
            district_name=F("district__name"),
        )[:limit]
    )


class Command(BaseCommand):
    help = (
        "Merge-import farmers from QUARTER 3/4 Excel files into existing live data "
        "(no delete)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--merge",
            action="store_true",
            help="Enable merge import mode for Q3/Q4 (required).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show preview only (default when --confirm is not passed).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Create backup and merge Q3/Q4 farmers into the database.",
        )
        parser.add_argument(
            "--quarter3",
            default=DEFAULT_QUARTER3_PATH,
            help=f'Path to "QUARTER 3GrpSum.xlsx" (default: {DEFAULT_QUARTER3_PATH}).',
        )
        parser.add_argument(
            "--quarter4",
            default=DEFAULT_QUARTER4_PATH,
            help=f'Path to "QUARTER 4GrpSum.xlsx" (default: {DEFAULT_QUARTER4_PATH}).',
        )
        parser.add_argument(
            "--backup-dir",
            default="",
            help="Directory for pg_dump backup (default: <project>/backups).",
        )

    def handle(self, *args, **options):
        if not options["merge"]:
            raise CommandError("Pass --merge to run Q3/Q4 merge import.")

        dry_run = options["dry_run"] or not options["confirm"]
        if options["dry_run"] and options["confirm"]:
            raise CommandError("Use either --dry-run or --confirm, not both.")

        q3_path = resolve_quarter_path(options["quarter3"], DEFAULT_QUARTER3_PATH)
        q4_path = resolve_quarter_path(options["quarter4"], DEFAULT_QUARTER4_PATH)
        mode = "dry-run" if dry_run else "confirm"

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Merge import environment (mode={mode})")
        )
        before_db = _print_db_context(self, "Database BEFORE merge import")
        farmers_before = Farmer.objects.count()
        villages_before = Village.objects.filter(is_active=True).count()

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Excel file paths"))
        for label, path in (("quarter3", q3_path), ("quarter4", q4_path)):
            self.stdout.write(
                f"  {label}: path={path!r} exists={path.exists()}"
            )

        if not q3_path.exists() and not q4_path.exists():
            raise CommandError("At least one of Q3/Q4 Excel files must exist.")

        for path, quarter_key in ((q3_path, "quarter3"), (q4_path, "quarter4")):
            if not path.exists():
                self.stdout.write(
                    self.style.WARNING(f"  Skipping missing file: {path}")
                )
                continue
            preview = preview_quarter_file(path, quarter_key)
            self.stdout.write(
                f"  {quarter_key} ({path.name}): {preview['rows_processed']} farmers, "
                f"{preview['village_count']} villages, "
                f"{len(preview['invalid_rows'])} invalid rows"
            )

        merge_preview = preview_merge_import(
            q3_path if q3_path.exists() else None,
            q4_path if q4_path.exists() else None,
        )
        if not merge_preview.get("ready"):
            raise CommandError("No farmers parsed from Q3/Q4 Excel files.")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Merge preview"))
        self.stdout.write(f"  Farmers before import: {farmers_before}")
        self.stdout.write(f"  Q3 parsed: {merge_preview['quarter3_parsed']}")
        self.stdout.write(f"  Q4 parsed: {merge_preview['quarter4_parsed']}")
        self.stdout.write(f"  New farmers expected: {merge_preview['farmers_created']}")
        self.stdout.write(
            f"  Duplicate farmers expected: {merge_preview['duplicates_skipped']}"
        )
        self.stdout.write(
            f"  New villages expected: {merge_preview['villages_created']}"
        )
        self.stdout.write(f"  Invalid rows: {len(merge_preview['invalid_rows'])}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only — no backup or import applied. "
                    "Re-run with --confirm to merge Q3/Q4."
                )
            )
            report = merge_preview.copy()
            report["mode"] = "dry-run"
            report["farmers_before"] = farmers_before
            report["villages_before"] = villages_before
            report["database"] = before_db
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        _require_excel_files(
            *(p for p in (q3_path, q4_path) if p.exists())
        )

        backup_dir = (
            Path(options["backup_dir"])
            if options["backup_dir"]
            else Path(settings.BASE_DIR) / "backups"
        )
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Backup before merge"))
        backup_path = create_db_backup(backup_dir)
        if not backup_path.exists() or backup_path.stat().st_size == 0:
            raise CommandError(f"Backup failed or empty: {backup_path}")
        self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_path}"))

        self.stdout.write(self.style.MIGRATE_HEADING("Merging Q3/Q4 farmers"))
        result = run_merge_import(
            q3_path if q3_path.exists() else None,
            q4_path if q4_path.exists() else None,
            dry_run=False,
        )

        _invalidate_caches()
        after_db = _print_db_context(self, "Database AFTER merge import")
        final_farmer_count = Farmer.objects.count()
        final_village_count = Village.objects.filter(is_active=True).count()

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("API verification"))
        api_results = _verify_apis(self)
        for path, info in api_results.items():
            if path == "error":
                self.stdout.write(self.style.WARNING(str(info)))
                continue
            ok = info.get("ok")
            style = self.style.SUCCESS if ok else self.style.ERROR
            extra = f" count={info['count']}" if info.get("count") is not None else ""
            self.stdout.write(style(f"  {path}: HTTP {info['status']}{extra}"))

        recent = _recent_merge_farmers(20)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Final summary"))
        self.stdout.write(f"  Old farmer count before import: {farmers_before}")
        self.stdout.write(f"  Farmers created: {result.farmers_created}")
        self.stdout.write(f"  Farmers updated: {result.farmers_updated}")
        self.stdout.write(f"  Duplicates skipped: {result.duplicates_skipped}")
        self.stdout.write(f"  Villages created: {result.villages_created}")
        self.stdout.write(f"  Invalid rows: {len(result.invalid_rows)}")
        self.stdout.write(f"  Final farmer count: {final_farmer_count}")
        self.stdout.write(f"  Villages before/after: {villages_before} -> {final_village_count}")
        self.stdout.write("  First 20 imported/updated farmers (Q3/Q4):")
        for row in recent:
            self.stdout.write(
                f"    id={row['id']} {row['name']!r} "
                f"village={row.get('village_name')!r} "
                f"phone={row.get('phone')!r} "
                f"source={row.get('source_quarter')!r}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Merge import complete."))
        summary_dict = result.to_dict()
        summary_dict["mode"] = "confirm"
        summary_dict["backup_path"] = str(backup_path)
        summary_dict["database_before"] = before_db
        summary_dict["database_after"] = after_db
        summary_dict["final_farmer_count"] = final_farmer_count
        summary_dict["villages_before"] = villages_before
        summary_dict["villages_after"] = final_village_count
        summary_dict["api_results"] = api_results
        summary_dict["recent_q3_q4_farmers"] = recent
        self.stdout.write(json.dumps(summary_dict, indent=2, default=str))
