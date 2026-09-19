"""Import operational villages + employee territory from Excel (village-only)."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from masters.operational_village_import import (
    collect_plan,
    execute_plan,
    format_plan,
)


class Command(BaseCommand):
    help = (
        "Import Village master + Employee↔Village assignments from Excel. "
        "Uses Village, village tamil name, and Field staff only. "
        "Ignores S NO / Firka / Taluk / District. Default is dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Path to .xlsx workbook")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report without writing (default).",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Write villages and assignments. Default is dry-run.",
        )

    def handle(self, *args, **options):
        # Avoid Windows cp1252 crashes on Tamil names in reports.
        try:
            self.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        execute = bool(options["execute"])
        dry_run = not execute

        try:
            plan = collect_plan(path)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(format_plan(plan, dry_run=dry_run))

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry-run only. No data was changed."))
            self.stdout.write("STOP.")
            return

        if plan.blocking_errors:
            raise CommandError(
                "Refusing --execute due to blocking errors: "
                + ", ".join(plan.blocking_errors)
                + ". Resolve EMPLOYEE_NOT_FOUND / AMBIGUOUS_EMPLOYEE / "
                "TAMIL_NAME_CONFLICT before production import."
            )

        try:
            result = execute_plan(plan)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("\nImport complete."))
        for key, value in result.items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write("PRODUCTION IMPORT EXECUTED: YES")
