"""
Print DB/API environment diagnostics for farmer import troubleshooting.
Does not delete or import anything.

Usage:
  python manage.py debug_farmer_environment
  python manage.py debug_farmer_environment --quarter1 "QUARTER 1GrpSum.xlsx" --quarter2 "QUARTER 2GrpSum.xlsx"
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from farmers.db_debug import (
    DEFAULT_QUARTER1_PATH,
    DEFAULT_QUARTER2_PATH,
    get_database_connection_info,
    preview_import_summary,
    probe_farmer_api_endpoints,
    resolve_quarter_paths,
)


class Command(BaseCommand):
    help = "Diagnose DB connection, farmer counts, Excel paths, and API endpoints (no mutations)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quarter1",
            default=DEFAULT_QUARTER1_PATH,
            help=f"Quarter 1 Excel path (default: {DEFAULT_QUARTER1_PATH}).",
        )
        parser.add_argument(
            "--quarter2",
            default=DEFAULT_QUARTER2_PATH,
            help=f"Quarter 2 Excel path (default: {DEFAULT_QUARTER2_PATH}).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output machine-readable JSON only.",
        )

    def handle(self, *args, **options):
        db_info = get_database_connection_info()
        files = resolve_quarter_paths(options["quarter1"], options["quarter2"])
        import_preview = preview_import_summary(
            options["quarter1"], options["quarter2"]
        )
        api = probe_farmer_api_endpoints()

        backups_dir = Path(settings.BASE_DIR) / "backups"
        recent_backups = sorted(backups_dir.glob("agri_clinic_pre_farmer_import_*.sql"))[-3:]

        report = {
            "database": db_info,
            "excel_files": files,
            "import_preview": import_preview,
            "api_endpoints": api,
            "recent_import_backups": [str(p) for p in recent_backups],
            "frontend_hints": {
                "local_admin_vite": "http://localhost:5173 - check VITE_API_BASE / .env",
                "local_backend": "http://localhost:8000/api/v1/admin/farmers/",
                "render_backend": "https://agri-clinic-backend.onrender.com/api/v1/admin/farmers/",
                "render_frontend": "https://agri-clinic-frontend.onrender.com",
                "note": (
                    "Admin SPA is not in this repo. In browser DevTools -> Network, "
                    "confirm the full URL of GET /api/v1/admin/farmers/ matches the DB below."
                ),
            },
            "likely_issue_if_old_data": (
                "No agri_clinic_pre_farmer_import_*.sql backup and "
                "source_quarter empty on all farmers -> --confirm was not run on this DB, "
                "or frontend calls a different backend (e.g. Render) than the shell command."
            ),
        }

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Database (this Django process)"))
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
            self.stdout.write(f"  {key}: {db_info.get(key)}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Table counts (SQL)"))
        for table in (
            "masters_farmer",
            "visits_visit",
            "masters_farmeractivity",
            "tracking_locationlog",
        ):
            self.stdout.write(f"  {table}: {db_info.get(f'count_{table}')}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Sample farmers (ORM)"))
        for row in db_info.get("sample_farmers") or []:
            self.stdout.write(
                f"  id={row['id']} name={row['name']!r} "
                f"source_quarter={row.get('source_quarter')!r}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Excel file paths"))
        for key, info in files.items():
            self.stdout.write(
                f"  {key}: path={info['path']!r} exists={info['exists']} "
                f"parsed_farmers={info['parsed_farmers']} "
                f"invalid_rows={info.get('invalid_rows', 0)}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Import preview"))
        if import_preview.get("ready"):
            self.stdout.write(
                f"  Q1 parsed: {import_preview['quarter1_parsed']} | "
                f"Q2 parsed: {import_preview['quarter2_parsed']} | "
                f"would create: {import_preview['farmers_created']} | "
                f"duplicates: {import_preview['duplicates_skipped']} | "
                f"invalid: {len(import_preview['invalid_rows'])}"
            )
        else:
            self.stdout.write(
                self.style.WARNING(f"  Not ready: {import_preview.get('reason')}")
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("API endpoint probe (same DB)"))
        for path, info in api.items():
            if path.startswith("_"):
                continue
            self.stdout.write(
                f"  {path}: HTTP {info.get('status')} count={info.get('count')}"
            )
        vs = api.get("_admin_viewset") or {}
        self.stdout.write(
            f"  Admin FarmerViewSet queryset count={vs.get('queryset_count')} "
            f"db_alias={vs.get('db_alias')}"
        )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Import backups (evidence of --confirm)"))
        if recent_backups:
            for p in recent_backups:
                self.stdout.write(f"  {p}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    "  None found in backups/ — clean_and_import_farmers --confirm "
                    "has not created a backup on this machine."
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(report["likely_issue_if_old_data"]))
