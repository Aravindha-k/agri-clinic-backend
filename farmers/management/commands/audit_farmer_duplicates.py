import json

from django.core.management.base import BaseCommand

from farmers.duplicate_audit import build_farmer_duplicate_audit


class Command(BaseCommand):
    help = "Read-only audit: duplicate farmers by phone, name+village, and cross-quarter overlap."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print full JSON report.",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=15,
            help="Max duplicate groups to print per section (default 15).",
        )

    def handle(self, *args, **options):
        report = build_farmer_duplicate_audit(group_limit=options["top"])
        summary = report["summary"]

        self.stdout.write(self.style.MIGRATE_HEADING("=== Farmer duplicate audit ===\n"))

        self.stdout.write(self.style.HTTP_INFO("COUNTS"))
        rows = [
            ("1. Total farmers (masters_farmer)", summary["total_farmers"]),
            ("2. Active farmers", summary["active_farmers"]),
            ("3. Inactive farmers", summary["inactive_farmers"]),
            ("4. Distinct phone numbers", summary["distinct_phone_numbers"]),
            ("5. Farmers with blank phone", summary["farmers_blank_phone"]),
            ("6. Duplicate phone groups", summary["duplicate_phone_groups"]),
            ("7. Duplicate name+village groups", summary["duplicate_name_village_groups"]),
            ("8. Likely duplicate records (safe groups)", summary["likely_duplicate_records"]),
            ("9. Safe merge candidate groups", summary["safe_merge_candidates"]),
            ("10. Unsafe/ambiguous duplicate groups", summary["unsafe_ambiguous_duplicates"]),
            ("11. Cross-quarter duplicate groups", summary["cross_quarter_duplicate_groups"]),
        ]
        for label, value in rows:
            self.stdout.write(f"  {label}: {value}")

        self.stdout.write(self.style.HTTP_INFO("\nQUARTER DISTRIBUTION (farmers may appear in multiple)"))
        for quarter, count in report.get("quarter_distribution", {}).items():
            self.stdout.write(f"  {quarter}: {count}")

        self.stdout.write(self.style.HTTP_INFO(f"\nNOTE: {summary['dashboard_count_note']}"))

        dup_phones = report["duplicate_phones"]
        if dup_phones:
            self.stdout.write(self.style.WARNING(f"\nDUPLICATE PHONE GROUPS ({len(dup_phones)} shown)"))
            for group in dup_phones:
                self.stdout.write(
                    f"\n  phone={group['phone']} count={group['farmer_count']} "
                    f"class={group['classification']} primary_id={group['primary_id']}"
                )
                for f in group["farmers"]:
                    self.stdout.write(
                        f"    id={f['id']} name={f['name']!r} village={f['village_id']} "
                        f"quarter={f['source_quarter']!r}"
                    )
        else:
            self.stdout.write(self.style.SUCCESS("\nNo duplicate phone groups."))

        dup_nv = report["duplicate_name_village"]
        if dup_nv:
            self.stdout.write(
                self.style.WARNING(f"\nDUPLICATE NAME+VILLAGE GROUPS ({len(dup_nv)} shown)")
            )
            for group in dup_nv:
                self.stdout.write(
                    f"\n  name={group['normalized_name']!r} village={group['village_id']} "
                    f"count={group['farmer_count']} class={group['classification']}"
                )
                for f in group["farmers"]:
                    self.stdout.write(
                        f"    id={f['id']} name={f['name']!r} phone={f['phone']!r} "
                        f"quarter={f['source_quarter']!r}"
                    )
        else:
            self.stdout.write(self.style.SUCCESS("\nNo duplicate name+village groups."))

        safe = report.get("safe_merge_groups") or []
        if safe:
            self.stdout.write(self.style.HTTP_INFO(f"\nSAFE MERGE CANDIDATES ({len(safe)} groups)"))
            for group in safe[: options["top"]]:
                ids = [f["id"] for f in group["farmers"]]
                self.stdout.write(f"  keep id={group['primary_id']} merge {ids}")
        else:
            self.stdout.write(self.style.SUCCESS("\nNo safe merge candidates."))

        ambiguous = report.get("ambiguous_groups") or []
        if ambiguous:
            self.stdout.write(
                self.style.ERROR(f"\nUNSAFE/AMBIGUOUS GROUPS ({len(ambiguous)} — manual review)")
            )
            for group in ambiguous[: options["top"]]:
                ids = [f["id"] for f in group["farmers"]]
                self.stdout.write(f"  ids={ids} class={group['classification']}")

        cross = report.get("cross_quarter_groups") or []
        if cross:
            self.stdout.write(self.style.WARNING(f"\nCROSS-QUARTER OVERLAP ({len(cross)} groups)"))
            for group in cross[: options["top"]]:
                self.stdout.write(
                    f"  ids={group.get('farmer_ids')} quarters={group.get('quarters')}"
                )

        self.stdout.write(
            self.style.HTTP_INFO(
                "\nNo data was modified. Next: python manage.py merge_farmer_duplicates --dry-run"
            )
        )

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
