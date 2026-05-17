from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from farmers.data_audit import build_agri_audit_report


class Command(BaseCommand):
    help = "Print farmer/visit audit summary (counts, status breakdown, duplicates)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output machine-readable JSON.",
        )

    def handle(self, *args, **options):
        report = build_agri_audit_report()
        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        f = report["farmers"]
        v = report["visits"]
        c = report["cleanup_candidates"]

        self.stdout.write(self.style.MIGRATE_HEADING("Agri Clinic data audit"))
        self.stdout.write("")
        self.stdout.write("Farmers:")
        self.stdout.write(f"  total farmers:        {f['total']}")
        self.stdout.write(f"  active farmers:       {f['active']}")
        self.stdout.write(f"  inactive farmers:     {f['inactive']}")
        self.stdout.write(f"  test name matches:    {f['test_pattern_matches']}")
        self.stdout.write(f"  clearly test (safe):  {f['clearly_test']}")
        self.stdout.write("")
        self.stdout.write("Visits:")
        self.stdout.write(f"  total visits:         {v['total_visits']}")
        self.stdout.write(f"  submitted valid:      {v['submitted_visits']}")
        self.stdout.write(f"  incomplete/orphan:    {v['incomplete_visits']}")
        self.stdout.write(f"  no farmer:            {v['no_farmer']}")
        self.stdout.write(f"  missing crop:         {v['missing_crop']}")
        self.stdout.write(f"  missing GPS:          {v['missing_gps']}")
        self.stdout.write("")
        self.stdout.write("Cleanup candidates (not deleted by this command):")
        self.stdout.write(f"  visits removable:     {c['visits_to_remove']}")
        self.stdout.write(f"  orphan (no farmer):   {c['orphan_no_farmer']}")
        self.stdout.write(f"  draft status rows:    {c['draft_status_incomplete']}")
        self.stdout.write("")
        self.stdout.write("Visits by status:")
        for row in report["visits_by_status"]:
            self.stdout.write(f"  {row['status']!r}: {row['count']}")
        self.stdout.write("")
        self.stdout.write("Submitted visits by farmer:")
        for row in report.get("submitted_by_farmer") or []:
            name = row.get("farmer__name") or "(no name)"
            self.stdout.write(
                f"  farmer_id={row['farmer_id']} {name}: {row['visit_count']}"
            )
        if not report.get("submitted_by_farmer"):
            self.stdout.write("  (none)")
        self.stdout.write("")
        self.stdout.write("Submitted visits by employee:")
        for row in report.get("submitted_by_employee") or v.get(
            "submitted_by_employee"
        ) or []:
            self.stdout.write(
                f"  {row.get('employee__username') or row.get('employee_username') or row['employee_id']}: "
                f"{row['visit_count']}"
            )
        if not (report.get("submitted_by_employee") or v.get("submitted_by_employee")):
            self.stdout.write("  (none)")
        self.stdout.write("")
        dup_f = report["duplicate_farmers_by_phone"]
        self.stdout.write(f"Duplicate farmers by mobile (top {len(dup_f)}):")
        if not dup_f:
            self.stdout.write("  (none)")
        for group in dup_f:
            self.stdout.write(f"  phone {group['phone']}: {group['count']} rows")
            for fr in group["farmers"]:
                self.stdout.write(
                    f"    id={fr['id']} name={fr['name']!r} active={fr['is_active']}"
                )
        self.stdout.write("")
        dup_v = report["duplicate_visits_by_slot"]
        self.stdout.write(f"Duplicate visits by farmer/employee/date/time (top {len(dup_v)}):")
        if not dup_v:
            self.stdout.write("  (none)")
        for group in dup_v:
            self.stdout.write(
                f"  farmer={group['farmer_id']} employee={group['employee_id']} "
                f"date={group['visit_date']} time={group['visit_time']}: "
                f"{group['c']} visits -> ids {group['visit_ids']}"
            )
        self.stdout.write("")
        self.stdout.write(
            self.style.NOTICE(
                "Dashboard KPIs should use: active farmers + submitted visits only. "
                "Run: python manage.py clean_test_agri_data --dry-run"
            )
        )
