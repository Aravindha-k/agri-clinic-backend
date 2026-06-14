"""
Audit and soft-deactivate problem categories not used by active problem items.

Usage:
  python manage.py clean_problem_categories --dry-run
  python manage.py clean_problem_categories --confirm
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient

from masters.problem_category_cleanup import (
    audit_problem_categories,
    deactivate_unused_problem_categories,
)
from masters.problem_item_utils import problem_categories_with_active_items
from masters.models import ProblemMaster


class Command(BaseCommand):
    help = (
        "Deactivate problem categories with zero active problem items "
        "(aligned with client Excel import data)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Audit only (default when --confirm is not passed).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Set is_active=False on unused categories.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or not options["confirm"]
        if options["dry_run"] and options["confirm"]:
            raise CommandError("Use either --dry-run or --confirm, not both.")

        audit = audit_problem_categories()

        self.stdout.write(self.style.MIGRATE_HEADING("Step 1 — Audit"))
        self.stdout.write(self.style.HTTP_INFO("All problem categories:"))
        for row in audit["all_categories"]:
            self.stdout.write(f"  {row}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Active problem items by category:"))
        for row in audit["counts_by_category"]:
            self.stdout.write(
                f"  {row['category__name']} ({row['category__code']}): "
                f"{row['active_item_count']}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Categories with zero active items:"))
        for row in audit["zero_item_categories"]:
            self.stdout.write(f"  {row['name']} ({row['code']}) active={row['is_active']}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Categories used in client import:"))
        for row in audit["client_import_categories"]:
            self.stdout.write(
                f"  {row['category__name']} ({row['category__code']}): "
                f"{row['active_item_count']}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 2 — Categories to keep"))
        for row in audit["categories_to_keep"]:
            self.stdout.write(f"  KEEP {row['name']} ({row['code']}) id={row['id']}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 3 — Categories to deactivate"))
        for row in audit["categories_to_deactivate"]:
            self.stdout.write(
                f"  DEACTIVATE {row['name']} ({row['code']}) id={row['id']}"
            )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry-run only — no changes applied."))
            self.stdout.write(json.dumps(audit, indent=2, default=str))
            return

        result = deactivate_unused_problem_categories(dry_run=False)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Deactivated: {result.deactivated_count}"))
        for row in result.deactivated:
            self.stdout.write(f"  id={row['id']} {row['name']} ({row['code']})")

        self._verify_apis()
        self.stdout.write(json.dumps(result.to_dict(), indent=2, default=str))

    def _verify_apis(self):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Step 6 — API verification"))

        User = get_user_model()
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            self.stdout.write(self.style.WARNING("No admin user for API probe."))
            return

        client = APIClient()
        client.force_authenticate(user=admin)

        r = client.get(
            "/api/v1/masters/problem-categories/dropdown/",
            HTTP_HOST="localhost",
        )
        dropdown = r.json().get("data", []) if r.status_code == 200 else []
        self.stdout.write(
            f"  GET problem-categories/dropdown/ HTTP {r.status_code} "
            f"count={len(dropdown)} codes={[x.get('code') for x in dropdown]}"
        )

        r2 = client.get(
            "/api/v1/masters/problem-masters/?category=pest",
            HTTP_HOST="localhost",
        )
        pest_items = r2.json().get("data", []) if r2.status_code == 200 else []
        self.stdout.write(
            f"  GET problem-masters/?category=pest HTTP {r2.status_code} "
            f"count={len(pest_items)}"
        )

        r3 = client.get("/api/v1/problem-items/?category=pest", HTTP_HOST="localhost")
        data = r3.json().get("data", {}) if r3.status_code == 200 else {}
        self.stdout.write(
            f"  GET problem-items/?category=pest HTTP {r3.status_code} "
            f"count={data.get('count')}"
        )

        self.stdout.write(
            f"  DB active problem items: "
            f"{ProblemMaster.objects.filter(is_active=True).count()}"
        )
        self.stdout.write(
            f"  Active categories with items: "
            f"{problem_categories_with_active_items().count()}"
        )
