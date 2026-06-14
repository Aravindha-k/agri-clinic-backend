import json

from django.core.management.base import BaseCommand, CommandError

from farmers.farmer_cleanup import create_db_backup
from farmers.merge_duplicates import execute_merge, preview_merge


class Command(BaseCommand):
    help = (
        "Merge safe farmer duplicates (same phone+village+name, or no-phone name+village). "
        "Keeps oldest farmer id; moves visits, fields, activities."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--dry-run",
            action="store_true",
            help="Show merge plan without modifying data.",
        )
        group.add_argument(
            "--confirm",
            action="store_true",
            help="Execute merge after creating a database backup.",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=50,
            help="Max duplicate groups to evaluate (default 50).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print JSON output.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            preview = preview_merge(group_limit=options["top"])
            summary = preview["audit_summary"]
            self.stdout.write(self.style.MIGRATE_HEADING("=== Farmer merge dry-run ===\n"))
            self.stdout.write(f"  Total farmers now: {summary['total_farmers']}")
            self.stdout.write(f"  Safe merge plans: {len(preview['merge_plans'])}")
            self.stdout.write(f"  Would delete rows: {preview['would_delete']}")
            self.stdout.write(
                f"  Ambiguous groups skipped: {preview['ambiguous_skipped']}"
            )
            if preview["merge_plans"]:
                self.stdout.write(self.style.HTTP_INFO("\nMERGE PLANS"))
                for plan in preview["merge_plans"]:
                    self.stdout.write(
                        f"  primary={plan['primary_id']} <- duplicate={plan['duplicate_id']} "
                        f"({plan['reason']})"
                    )
            else:
                self.stdout.write(self.style.SUCCESS("\nNothing to merge."))
            if options["json"]:
                self.stdout.write(json.dumps(preview, indent=2, default=str))
            return

        self.stdout.write(self.style.WARNING("Creating database backup…"))
        try:
            backup_path = create_db_backup()
        except CommandError as exc:
            raise CommandError(f"Backup failed — aborting merge: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Backup saved: {backup_path}"))

        result = execute_merge(group_limit=options["top"])
        post = result["post_audit_summary"]

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Merge complete ==="))
        self.stdout.write(f"  Merged duplicate rows: {result['merged']}")
        self.stdout.write(f"  Final farmer count: {post['total_farmers']}")
        self.stdout.write(f"  Duplicate phone groups remaining: {post['duplicate_phone_groups']}")
        self.stdout.write(
            f"  Duplicate name+village groups remaining: {post['duplicate_name_village_groups']}"
        )
        self.stdout.write(f"  Safe merge candidates remaining: {post['safe_merge_candidates']}")

        if options["json"]:
            self.stdout.write(json.dumps(result, indent=2, default=str))
