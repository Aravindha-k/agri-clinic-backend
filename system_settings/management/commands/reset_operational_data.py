"""
Reset old field operational data so Kavya Agri Clinic can start fresh.

Default is dry-run. Nothing is deleted unless ALL of the following are set:

  python manage.py reset_operational_data --execute \\
      --confirm-phrase="RESET KAVYA OPERATIONAL DATA"

Production also requires --allow-production.

This command does NOT delete employees, users, passwords, or reusable
crop/problem masters. Physical media files are reported, not deleted.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from system_settings.operational_reset import (
    CONFIRM_PHRASE,
    collect_plan,
    critical_counts,
    execute_reset,
    format_plan,
    is_production_env,
    plans_equal,
    post_reset_counts,
)


class Command(BaseCommand):
    help = (
        "Dry-run by default. Delete old location/farmer/visit/tracking "
        "operational data only with --execute and the confirmation phrase. "
        "Never deletes employees or auth accounts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Perform the reset. Default is dry-run (no deletes).",
        )
        parser.add_argument(
            "--confirm-phrase",
            default="",
            help=f'Must equal "{CONFIRM_PHRASE}" when --execute is used.',
        )
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="Required when APP_ENV is production/staging. Extra safeguard.",
        )

    def handle(self, *args, **options):
        execute = bool(options["execute"])
        phrase = (options.get("confirm_phrase") or "").strip()

        if execute:
            if is_production_env() and not options["allow_production"]:
                raise CommandError(
                    "Refusing to reset operational data in production. "
                    "Dry-run is allowed. Destructive run requires "
                    "--allow-production AND the confirmation phrase. "
                    "Do not run this until explicitly approved."
                )
            if phrase != CONFIRM_PHRASE:
                raise CommandError(
                    "Destructive reset refused. Re-run with:\n"
                    f'  --execute --confirm-phrase="{CONFIRM_PHRASE}"\n'
                    "Default invocation is dry-run and deletes nothing."
                )

        before = critical_counts()
        plan = collect_plan()
        self.stdout.write(format_plan(plan, dry_run=not execute))

        if not execute:
            after_plan = collect_plan()
            after = critical_counts()
            unchanged = plans_equal(plan, after_plan) and list(before.items()) == list(
                after.items()
            )
            self.stdout.write("")
            self.stdout.write("--- POST-DRY-RUN VERIFICATION ---")
            for name, n in after.items():
                self.stdout.write(f"{name}: {n}")
            self.stdout.write("")
            if unchanged:
                self.stdout.write(
                    self.style.SUCCESS("DRY RUN ZERO WRITES VERIFIED: YES")
                )
            else:
                self.stdout.write(self.style.ERROR("DRY RUN ZERO WRITES VERIFIED: NO"))
                self.stdout.write("Counts changed during dry-run. Abort and inspect.")
                raise CommandError("Dry-run appeared to change counts.")
            self.stdout.write(self.style.WARNING("\nDry-run only. No data was changed."))
            return

        deleted = execute_reset()
        self.stdout.write(self.style.SUCCESS("\nReset complete (database rows only)."))
        for name, n in deleted.items():
            self.stdout.write(f"  deleted collector count {name}: {n}")
        self.stdout.write("\nPOST-RESET COUNTS")
        for name, n in post_reset_counts().items():
            self.stdout.write(f"  {name}: {n}")
        self.stdout.write(
            "Media files were NOT deleted. Review PHYSICAL MEDIA above for orphan cleanup."
        )
