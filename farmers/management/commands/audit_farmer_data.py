import json

from django.core.management.base import BaseCommand

from farmers.audit import build_farmer_data_audit, build_farmer_visit_audit


class Command(BaseCommand):
    help = "Read-only audit: Farmer uniqueness, phone duplicates, Visit linkage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print full JSON report.",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=10,
            help="Number of top farmers by visit count (default 10).",
        )

    def handle(self, *args, **options):
        report = build_farmer_data_audit(top_n=options["top"])
        visit_report = build_farmer_visit_audit(orphan_limit=30, farmer_limit=50)
        summary = report["summary"]
        schema = report["schema"]

        self.stdout.write(self.style.MIGRATE_HEADING("=== Farmer / Visit DB audit ===\n"))

        self.stdout.write(self.style.HTTP_INFO("COUNTS"))
        rows = [
            ("1. Total Farmer records", summary["total_farmers"]),
            ("2. Total Visit records", summary["total_visits"]),
            ("3. Distinct farmer_id in Visit", summary["distinct_farmer_id_in_visits"]),
            ("4. Distinct phone in Farmer", summary["distinct_phone_numbers"]),
            ("5. Duplicate phone groups", summary["duplicate_phone_groups"]),
            ("6. Farmers blank/null phone", summary["farmers_blank_phone"]),
            ("7. Visits farmer_id IS NULL", summary["visits_without_farmer_id"]),
            ("8. Visits broken farmer FK", summary["visits_broken_farmer_fk"]),
            ("9. Farmers with zero visits", summary["farmers_with_zero_visits"]),
            ("   Orphan visits (no FK)", summary["orphan_visits"]),
        ]
        for label, value in rows:
            self.stdout.write(f"  {label}: {value}")

        self.stdout.write(self.style.HTTP_INFO("\nPHONE UNIQUENESS (Farmer.phone)"))
        self.stdout.write(f"  Field: {schema['field_name']} ({schema['note']})")
        self.stdout.write(f"  unique=True on field: {schema['unique_on_field']}")
        self.stdout.write(f"  db_index on field: {schema['db_index_on_field']}")
        self.stdout.write(f"  DB unique indexes on phone: {len(schema['db_unique_indexes_on_phone'])}")
        self.stdout.write(f"  tenant field exists: {schema['has_tenant_field']}")
        self.stdout.write(
            f"  tenant+phone constraint: {schema['has_tenant_plus_mobile_constraint']}"
        )
        self.stdout.write(f"  => {schema['uniqueness_summary']}")

        if schema.get("suggested_production_migration"):
            self.stdout.write(self.style.WARNING("\nSuggested migration (after dedup):"))
            self.stdout.write(schema["suggested_production_migration"])

        dupes = report["duplicate_phones"]
        if dupes:
            self.stdout.write(self.style.WARNING(f"\nDUPLICATE PHONES ({len(dupes)} groups)"))
            for group in dupes:
                self.stdout.write(f"\n  phone={group['phone']} ({group['farmer_count']} farmers)")
                for f in group["farmers"]:
                    self.stdout.write(
                        f"    id={f['id']} name={f['name']!r} visits={f['visit_count']} "
                        f"active={f['is_active']} code={f['farmer_code']}"
                    )
                self.stdout.write(f"    merge_hint: {group['merge_hint']}")
        else:
            self.stdout.write(self.style.SUCCESS("\nNo duplicate phone numbers."))

        if report["farmers_blank_phone"]:
            self.stdout.write(self.style.WARNING("\nBLANK PHONE FARMERS"))
            for f in report["farmers_blank_phone"]:
                self.stdout.write(f"  id={f['id']} name={f['name']!r}")

        if report["visits_broken_farmer_fk"]:
            self.stdout.write(self.style.ERROR("\nBROKEN FK VISITS (farmer_id not in Farmer)"))
            for v in report["visits_broken_farmer_fk"]:
                self.stdout.write(
                    f"  visit_id={v['id']} farmer_id={v['farmer_id']} "
                    f"name={v['farmer_name']!r} phone={v['farmer_phone']!r}"
                )

        self.stdout.write(self.style.HTTP_INFO(f"\nTOP FARMERS BY VISITS (top {options['top']})"))
        for f in report["top_farmers_by_visits"]:
            self.stdout.write(
                f"  id={f['id']} {f['name']!r} phone={f['phone']} visits={f['visit_count']}"
            )

        zero = report["farmers_with_zero_visits"]
        if zero:
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"\nFARMERS WITH ZERO VISITS (showing {len(zero)} of "
                    f"{summary['farmers_with_zero_visits']})"
                )
            )
            for f in zero[:15]:
                self.stdout.write(f"  id={f['id']} {f['name']!r} phone={f['phone']}")

        orphans = report["orphan_visits_sample"]
        if orphans:
            self.stdout.write(
                self.style.WARNING(
                    f"\nORPHAN VISITS sample ({len(orphans)} shown, "
                    f"{summary['orphan_visits']} total)"
                )
            )
            for v in orphans[:10]:
                self.stdout.write(
                    f"  visit_id={v['id']} {v['farmer_name']!r} / {v['farmer_phone']}"
                )

        integrity = visit_report.get("integrity", {})
        if integrity:
            self.stdout.write(self.style.HTTP_INFO("\nLINKAGE (safe match preview)"))
            self.stdout.write(
                f"  linkable to existing farmer: {integrity.get('orphan_visits_linkable_without_new_farmer', 0)}"
            )
            self.stdout.write(
                f"  ambiguous match: {integrity.get('orphan_visits_ambiguous_match', 0)}"
            )
            self.stdout.write(
                f"  no match: {integrity.get('orphan_visits_no_match', 0)}"
            )

        self.stdout.write(
            self.style.HTTP_INFO(
                "\nNo data was modified. Use link_visits_to_farmers --apply only after review."
            )
        )

        if options["json"]:
            full = {**report, "visit_linkage": visit_report}
            self.stdout.write(json.dumps(full, indent=2, default=str))
