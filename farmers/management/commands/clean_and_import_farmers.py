"""
Clean old farmer-related transactional data and import live farmers from quarter Excel files.

Usage:
  python manage.py clean_and_import_farmers --dry-run
  python manage.py clean_and_import_farmers --confirm \\
      --quarter1 "QUARTER 1GrpSum.xlsx" --quarter2 "QUARTER 2GrpSum.xlsx"
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.test import Client
from rest_framework import status

from farmers.db_debug import (
    DEFAULT_QUARTER1_PATH,
    DEFAULT_QUARTER2_PATH,
    get_database_connection_info,
    preview_import_summary,
    probe_farmer_api_endpoints,
    resolve_quarter_path,
    resolve_quarter_paths,
)
from masters.models import Farmer
from farmers.farmer_cleanup import (
    audit_table_classification,
    count_delete_plan,
    create_db_backup,
    execute_farmer_cleanup,
    farmer_delete_plan,
)
from farmers.farmer_quarter_import import ImportSummary, preview_quarter_file, run_full_import


def _print_db_context(command: BaseCommand, heading: str) -> dict:
    command.stdout.write("")
    command.stdout.write(command.style.MIGRATE_HEADING(heading))
    info = get_database_connection_info()
    for key in (
        "engine",
        "name",
        "host",
        "port",
        "user",
        "current_database",
        "inet_server_addr",
        "database_url_host",
        "app_env",
    ):
        command.stdout.write(f"  {key}: {info.get(key)}")
    for table in (
        "masters_farmer",
        "visits_visit",
        "masters_farmeractivity",
        "tracking_locationlog",
    ):
        command.stdout.write(f"  COUNT {table}: {info.get(f'count_{table}')}")
    command.stdout.write("  Sample farmers (first 5 by id):")
    for row in info.get("sample_farmers") or []:
        command.stdout.write(
            f"    id={row['id']} name={row['name']!r} "
            f"source_quarter={row.get('source_quarter')!r}"
        )
    return info


def _print_excel_paths(command: BaseCommand, quarter1: str, quarter2: str) -> None:
    command.stdout.write("")
    command.stdout.write(command.style.MIGRATE_HEADING("Excel file paths"))
    for key, info in resolve_quarter_paths(quarter1, quarter2).items():
        command.stdout.write(
            f"  {key}: path={info['path']!r} exists={info['exists']} "
            f"parsed_farmers={info['parsed_farmers']} "
            f"invalid_rows={info.get('invalid_rows', 0)}"
        )


def _require_excel_files(q1: Path, q2: Path) -> None:
    missing = [str(p) for p in (q1, q2) if not p.exists()]
    if missing:
        raise CommandError(
            "Excel file(s) missing — place files under imports/ and retry:\n  "
            + "\n  ".join(missing)
        )


def _first_imported_farmers(limit: int = 10) -> list[dict]:
    return list(
        Farmer.objects.select_related("village", "district")
        .order_by("id")
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


def _verify_apis(command: BaseCommand) -> dict:
    """Smoke-check farmer list APIs after import."""
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()
    if admin is None:
        admin = User.objects.filter(is_staff=True).first()

    results: dict[str, dict] = {}
    if admin is None:
        return {"error": "No admin user found for API verification"}

    client = Client()
    client.force_login(admin)

    paths = [
        "/api/v1/admin/farmers/",
        "/api/v1/farmers/",
        "/api/v1/masters/villages/",
    ]
    for path in paths:
        resp = client.get(path, HTTP_HOST="localhost")
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.content[:200].decode("utf-8", errors="replace")}
        count = None
        if isinstance(body, dict):
            data = body.get("data", body)
            if isinstance(data, dict) and "count" in data:
                count = data["count"]
            elif isinstance(data, list):
                count = len(data)
            elif isinstance(data, dict) and "results" in data:
                count = data.get("count", len(data["results"]))
        results[path] = {
            "status": resp.status_code,
            "count": count,
            "ok": resp.status_code == status.HTTP_200_OK,
        }

    from masters.models import Farmer, Village

    sample_village = Village.objects.order_by("name").values_list("name", flat=True).first()
    if sample_village:
        for base in ("/api/v1/farmers/", "/api/v1/admin/farmers/"):
            path = f"{base}?village={sample_village}"
            resp = client.get(path, HTTP_HOST="localhost")
            results[path] = {
                "status": resp.status_code,
                "ok": resp.status_code == status.HTTP_200_OK,
            }
        farmer = Farmer.objects.order_by("name").first()
        if farmer:
            search_path = f"/api/v1/farmers/?search={farmer.name[:12]}"
            resp = client.get(search_path, HTTP_HOST="localhost")
            results[search_path] = {
                "status": resp.status_code,
                "ok": resp.status_code == status.HTTP_200_OK,
            }

    return results


class Command(BaseCommand):
    help = (
        "Audit and delete old farmer-related data, then import farmers from "
        "QUARTER 1/2 group summary Excel files."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show audit counts and import preview without deleting or writing.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Create backup, delete old farmer data, and import Excel files.",
        )
        parser.add_argument(
            "--quarter1",
            default=DEFAULT_QUARTER1_PATH,
            help=f'Path to "QUARTER 1GrpSum.xlsx" (default: {DEFAULT_QUARTER1_PATH}).',
        )
        parser.add_argument(
            "--quarter2",
            default=DEFAULT_QUARTER2_PATH,
            help=f'Path to "QUARTER 2GrpSum.xlsx" (default: {DEFAULT_QUARTER2_PATH}).',
        )
        parser.add_argument(
            "--backup-dir",
            default="",
            help="Directory for pg_dump backup (default: <project>/backups).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or not options["confirm"]
        if options["dry_run"] and options["confirm"]:
            raise CommandError("Use either --dry-run or --confirm, not both.")

        quarter1 = options["quarter1"] or DEFAULT_QUARTER1_PATH
        quarter2 = options["quarter2"] or DEFAULT_QUARTER2_PATH
        q1_path = resolve_quarter_path(quarter1, DEFAULT_QUARTER1_PATH)
        q2_path = resolve_quarter_path(quarter2, DEFAULT_QUARTER2_PATH)
        mode = "dry-run" if dry_run else "confirm"

        self.stdout.write(self.style.MIGRATE_HEADING(f"Environment check (mode={mode})"))
        before_db = _print_db_context(self, "Database BEFORE delete/import")
        _print_excel_paths(self, quarter1, quarter2)

        import_preview = preview_import_summary(quarter1, quarter2)
        if import_preview.get("ready"):
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("Import preview (dry-run)"))
            self.stdout.write(
                f"  Q1 parsed: {import_preview['quarter1_parsed']} | "
                f"Q2 parsed: {import_preview['quarter2_parsed']} | "
                f"would create: {import_preview['farmers_created']} | "
                f"duplicates skipped: {import_preview['duplicates_skipped']} | "
                f"invalid rows: {len(import_preview['invalid_rows'])}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 1: Audit"))
        sections = audit_table_classification()
        for label, key in (
            ("A. KEEP", "KEEP"),
            ("B. DELETE", "DELETE"),
            ("C. UNSURE", "UNSURE"),
        ):
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO(f"=== {label} ==="))
            for row in sections[key]:
                count = row["count"]
                count_s = str(count) if count >= 0 else "?"
                self.stdout.write(f"  {row['table']}: {count_s} — {row['note']}")

        plan = farmer_delete_plan()
        delete_counts = count_delete_plan(plan)
        total_delete = sum(c for c in delete_counts.values() if c > 0)
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Rows that would be deleted (farmer-related):"))
        for table, count in delete_counts.items():
            if count > 0:
                self.stdout.write(f"  {table}: {count}")
        self.stdout.write(f"  TOTAL: {total_delete}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 3 preview: Excel import"))
        summary = ImportSummary()
        summary.deleted_counts = {k: v for k, v in delete_counts.items() if v > 0}

        for p, quarter_key in ((q1_path, "quarter1"), (q2_path, "quarter2")):
            if not p.exists():
                self.stdout.write(self.style.ERROR(f"  {quarter_key}: file not found: {p}"))
                continue
            preview = preview_quarter_file(p, quarter_key)
            self.stdout.write(
                f"  {quarter_key} ({p.name}): {preview['rows_processed']} farmers, "
                f"{preview['village_count']} villages, "
                f"{len(preview['invalid_rows'])} invalid rows"
            )
            if preview["sample_farmers"]:
                self.stdout.write("    Sample:")
                for sample in preview["sample_farmers"][:5]:
                    self.stdout.write(
                        f"      {sample['village']} | {sample['name']} | {sample['phone'] or '(no phone)'}"
                    )

        if import_preview.get("ready"):
            summary.quarter1_rows_processed = import_preview["quarter1_parsed"]
            summary.quarter2_rows_processed = import_preview["quarter2_parsed"]
            summary.farmers_created = import_preview["farmers_created"]
            summary.farmers_updated = import_preview.get("farmers_updated", 0)
            summary.duplicates_skipped = import_preview["duplicates_skipped"]
            summary.invalid_rows = import_preview["invalid_rows"]
            summary.village_count = import_preview["village_count"]
            summary.district = import_preview["district"]

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only — no backup, delete, or import applied. "
                    "Re-run with --confirm (not --dry-run) to apply changes."
                )
            )
            summary_dict = summary.to_dict()
            summary_dict["database_before"] = before_db
            summary_dict["mode"] = "dry-run"
            self.stdout.write(json.dumps(summary_dict, indent=2, default=str))
            return

        _require_excel_files(q1_path, q2_path)
        if not import_preview.get("ready"):
            raise CommandError(import_preview.get("reason", "Import preview failed"))
        total_parsed = (
            import_preview["quarter1_parsed"] + import_preview["quarter2_parsed"]
        )
        if total_parsed == 0:
            raise CommandError("No farmers parsed from Excel files — aborting.")

        backup_dir = (
            Path(options["backup_dir"])
            if options["backup_dir"]
            else Path(settings.BASE_DIR) / "backups"
        )
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 2: Backup + delete"))
        backup_path = create_db_backup(backup_dir)
        if not backup_path.exists() or backup_path.stat().st_size == 0:
            raise CommandError(f"Backup failed or empty: {backup_path}")
        self.stdout.write(self.style.SUCCESS(f"Backup created: {backup_path}"))

        with transaction.atomic():
            deleted = execute_farmer_cleanup(plan)
            summary.deleted_counts = deleted

            after_delete_db = _print_db_context(
                self, "Database IMMEDIATELY AFTER delete (before import)"
            )
            farmer_count_after_delete = Farmer.objects.count()
            if farmer_count_after_delete != 0:
                raise CommandError(
                    f"Delete incomplete: masters_farmer count is "
                    f"{farmer_count_after_delete}, expected 0. Rolling back."
                )

            self.stdout.write(self.style.MIGRATE_HEADING("Step 3: Import live farmers"))
            import_result = run_full_import(q1_path, q2_path, dry_run=False)
            summary.quarter1_rows_processed = import_result.quarter1_rows_processed
            summary.quarter2_rows_processed = import_result.quarter2_rows_processed
            summary.farmers_created = import_result.farmers_created
            summary.farmers_updated = import_result.farmers_updated
            summary.duplicates_skipped = import_result.duplicates_skipped
            summary.invalid_rows = import_result.invalid_rows
            summary.village_count = import_result.village_count
            summary.district = import_result.district

        _invalidate_caches()

        after_import_db = _print_db_context(self, "Database AFTER import")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 4: Verify APIs"))
        api_probe = probe_farmer_api_endpoints()
        for path, info in api_probe.items():
            if path.startswith("_"):
                continue
            self.stdout.write(
                f"  {path}: HTTP {info.get('status')} count={info.get('count')}"
            )
        vs = api_probe.get("_admin_viewset") or {}
        self.stdout.write(
            f"  Admin FarmerViewSet: count={vs.get('queryset_count')} "
            f"sample={vs.get('sample')}"
        )

        api_results = _verify_apis(self)
        for path, info in api_results.items():
            if path == "error":
                self.stdout.write(self.style.WARNING(str(info)))
                continue
            ok = info.get("ok")
            style = self.style.SUCCESS if ok else self.style.ERROR
            extra = f" count={info['count']}" if info.get("count") is not None else ""
            self.stdout.write(style(f"  {path}: HTTP {info['status']}{extra}"))

        first_twenty = _first_imported_farmers(20)
        final_farmer_count = Farmer.objects.count()

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Final summary"))
        self.stdout.write(f"  Old rows deleted: {sum(deleted.values())}")
        self.stdout.write(f"  Farmers created: {summary.farmers_created}")
        self.stdout.write(f"  Farmers updated: {summary.farmers_updated}")
        self.stdout.write(f"  Duplicates skipped: {summary.duplicates_skipped}")
        self.stdout.write(f"  Invalid rows: {len(summary.invalid_rows)}")
        self.stdout.write(f"  Final farmer count: {final_farmer_count}")
        self.stdout.write("  First 20 imported farmers:")
        for row in first_twenty:
            self.stdout.write(
                f"    id={row['id']} {row['name']!r} "
                f"village={row.get('village_name')!r} "
                f"phone={row.get('phone')!r} "
                f"source={row.get('source_quarter')!r}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Clean and import complete."))
        summary_dict = summary.to_dict()
        summary_dict["mode"] = "confirm"
        summary_dict["backup_path"] = str(backup_path)
        summary_dict["database_before"] = before_db
        summary_dict["database_after_delete"] = after_delete_db
        summary_dict["database_after_import"] = after_import_db
        summary_dict["api_probe"] = api_probe
        summary_dict["final_farmer_count"] = final_farmer_count
        summary_dict["first_20_imported_farmers"] = first_twenty
        self.stdout.write(json.dumps(summary_dict, indent=2, default=str))
