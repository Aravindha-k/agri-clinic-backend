"""Verify production DATABASE_URL resolves and django_migrations exists."""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Log active DB host and confirm django_migrations is reachable."

    def handle(self, *args, **options):
        db_url = getattr(settings, "DATABASE_URL", "") or ""
        host = (urlsplit(db_url).hostname or "").strip() or "(unset)"
        engine = settings.DATABASES["default"].get("ENGINE", "")

        self.stdout.write(f"DATABASE_URL host: {host}")
        self.stdout.write(f"DB engine: {engine}")

        if "sqlite" in engine:
            self.stdout.write(self.style.WARNING("Skipping migration check (sqlite)"))
            return

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'django_migrations'"
            )
            row = cursor.fetchone()

        if not row or row[0] < 1:
            self.stderr.write(self.style.ERROR("django_migrations table not found"))
            raise SystemExit(1)

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            migration_count = cursor.fetchone()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"django_migrations OK ({migration_count} migration records)"
            )
        )
