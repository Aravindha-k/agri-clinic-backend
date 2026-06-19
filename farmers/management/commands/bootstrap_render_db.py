"""
Bootstrap a fresh Render PostgreSQL database: migrate, admin, fixture, farmer imports.

Usage (after setting DATABASE_URL to the NEW Render Postgres instance):

  set APP_ENV=production
  set RENDER=true
  set BOOTSTRAP_ADMIN_PASSWORD=<strong-password>
  python manage.py bootstrap_render_db --confirm

Optional fixture (users, employees, masters from local export):

  python manage.py bootstrap_render_db --confirm --fixture local_export_for_render.json
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from farmers.db_debug import get_database_connection_info
from farmers.management.commands.clean_and_import_farmers import _verify_apis
from masters.models import Crop, District, Farmer, Village


class Command(BaseCommand):
    help = (
        "Migrate and seed a new Render Postgres DB: optional fixture, admin user, "
        "QUARTER 1–4 farmer Excel imports."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Run writes (migrate, import, seed). Without this, dry-run only.",
        )
        parser.add_argument(
            "--fixture",
            default="",
            help="Optional dumpdata JSON (e.g. local_export_for_render.json) for users/employees.",
        )
        parser.add_argument(
            "--skip-farmers",
            action="store_true",
            help="Skip Excel farmer imports (migrate + admin/fixture only).",
        )
        parser.add_argument(
            "--skip-quarters-merge",
            action="store_true",
            help="Skip QUARTER 3/4 merge import.",
        )
        parser.add_argument(
            "--admin-username",
            default="",
            help="Bootstrap superuser username (default: BOOTSTRAP_ADMIN_USERNAME or renderadmin).",
        )
        parser.add_argument(
            "--admin-email",
            default="",
            help="Bootstrap superuser email (default: BOOTSTRAP_ADMIN_EMAIL).",
        )

    def handle(self, *args, **options):
        confirm = options["confirm"]
        mode = "CONFIRM" if confirm else "DRY-RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Render DB bootstrap ({mode})"))

        self._assert_postgres_target(confirm=confirm)
        self._print_db_info()

        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only. Re-run with --confirm after updating Render DATABASE_URL."
                )
            )
            self._preview_imports()
            return

        self.stdout.write(self.style.HTTP_INFO("Step 1/6: migrate"))
        call_command("migrate", "--noinput", verbosity=1)

        self.stdout.write(self.style.HTTP_INFO("Step 2/6: verify_production_db"))
        call_command("verify_production_db", verbosity=1)

        fixture = (options["fixture"] or "").strip()
        if fixture:
            path = Path(fixture)
            if not path.is_file():
                raise CommandError(f"Fixture not found: {path}")
            self.stdout.write(self.style.HTTP_INFO(f"Step 3/6: loaddata {path.name}"))
            call_command("loaddata", str(path), verbosity=1)
        else:
            self.stdout.write(self.style.HTTP_INFO("Step 3/6: fixture skipped"))

        admin = self._ensure_admin(
            username=options["admin_username"],
            email=options["admin_email"],
        )
        self.stdout.write(
            self.style.SUCCESS(f"Admin ready: username={admin.username} (staff/superuser)")
        )

        if not options["skip_farmers"]:
            self.stdout.write(
                self.style.HTTP_INFO("Step 4/6: clean_and_import_farmers (Q1 + Q2)")
            )
            call_command(
                "clean_and_import_farmers",
                "--confirm",
                verbosity=1,
            )
        else:
            self.stdout.write(self.style.HTTP_INFO("Step 4/6: farmer import skipped"))

        if not options["skip_farmers"] and not options["skip_quarters_merge"]:
            self.stdout.write(
                self.style.HTTP_INFO("Step 5/6: import_farmers_quarters merge (Q3 + Q4)")
            )
            call_command(
                "import_farmers_quarters",
                "--merge",
                "--confirm",
                verbosity=1,
            )
        else:
            self.stdout.write(self.style.HTTP_INFO("Step 5/6: Q3/Q4 merge skipped"))

        self.stdout.write(self.style.HTTP_INFO("Step 6/6: final counts + API smoke"))
        self._print_counts()
        api_results = _verify_apis(self)
        for path, info in api_results.items():
            if path == "error":
                self.stdout.write(self.style.WARNING(f"  API verify: {info}"))
                continue
            ok = info.get("ok")
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"  {path} -> {info.get('status')} count={info.get('count')}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bootstrap complete."))
        self.stdout.write(
            "Next: update Render Dashboard → agri-clinic-backend → DATABASE_URL "
            "(if not already), redeploy, then GET /healthz/ and test login."
        )

    def _assert_postgres_target(self, *, confirm: bool = False) -> None:
        engine = settings.DATABASES["default"].get("ENGINE", "")
        if "sqlite" in engine:
            raise CommandError(
                "DATABASE_URL points to sqlite. Set production Postgres DATABASE_URL first."
            )
        db_url = getattr(settings, "DATABASE_URL", "") or os.getenv("DATABASE_URL", "")
        host = (urlsplit(db_url).hostname or "").strip().lower()
        blocked = {
            "dpg-d7ckj7dckfvc739s0frg-a",
            "dpg-d7ckj7dckfvc739s0frg-a.singapore-postgres.render.com",
            "dpg-d84t75d7vvec73fhlpfg-a",
            "dpg-d84t75d7vvec73fhlpfg-a.singapore-postgres.render.com",
        }
        short = host.split(".")[0] if host else ""
        if host in blocked or short in blocked:
            self.stdout.write(
                self.style.WARNING(
                    f"DATABASE_URL host {host or short} is the suspended/old instance. "
                    "Create a NEW Render Postgres and paste its URL before --confirm."
                )
            )
            if confirm and not os.getenv("BOOTSTRAP_ALLOW_OLD_HOST"):
                raise CommandError(
                    "Refusing to bootstrap suspended DB host. Set BOOTSTRAP_ALLOW_OLD_HOST=1 to override."
                )

    def _print_db_info(self) -> None:
        db_url = getattr(settings, "DATABASE_URL", "") or os.getenv("DATABASE_URL", "")
        host = (urlsplit(db_url).hostname or "").strip() or "(unset)"
        engine = settings.DATABASES["default"].get("ENGINE", "")
        self.stdout.write(f"  engine: {engine}")
        self.stdout.write(f"  database_url_host: {host}")
        self.stdout.write(f"  app_env: {os.getenv('APP_ENV', '')}")
        try:
            info = get_database_connection_info()
            for key in ("name", "host", "user", "current_database"):
                self.stdout.write(f"  {key}: {info.get(key)}")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  live connection: unavailable ({exc.__class__.__name__})"))

    def _preview_imports(self) -> None:
        from farmers.farmer_quarter_import import preview_quarter_file
        from farmers.db_debug import resolve_quarter_path

        for quarter_key, default in (
            ("quarter1", "imports/QUARTER 1GrpSum.xlsx"),
            ("quarter2", "imports/QUARTER 2GrpSum.xlsx"),
        ):
            path = resolve_quarter_path(default, default)
            if not path.exists():
                self.stdout.write(self.style.WARNING(f"  {quarter_key}: missing {path}"))
                continue
            prev = preview_quarter_file(path, quarter_key)
            self.stdout.write(
                f"  {quarter_key}: farmers={prev.get('farmer_count', 0)} "
                f"invalid={len(prev.get('invalid_rows', []))}"
            )

    def _ensure_admin(self, *, username: str, email: str):
        User = get_user_model()
        existing = User.objects.filter(is_superuser=True).order_by("id").first()
        if existing:
            return existing

        username = (
            username.strip()
            or os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
            or "renderadmin"
        )
        email = (
            email.strip()
            or os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
            or "admin@agri-clinic.local"
        )
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
        if not password:
            raise CommandError(
                "No superuser in DB. Set BOOTSTRAP_ADMIN_PASSWORD (and optionally "
                "BOOTSTRAP_ADMIN_USERNAME) before --confirm."
            )
        return User.objects.create_superuser(username, email, password)

    def _print_counts(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            migrations = cursor.fetchone()[0]
        self.stdout.write(f"  django_migrations: {migrations}")
        self.stdout.write(f"  farmers: {Farmer.objects.count()}")
        self.stdout.write(f"  villages: {Village.objects.count()}")
        self.stdout.write(f"  districts: {District.objects.count()}")
        self.stdout.write(f"  crops: {Crop.objects.count()}")
