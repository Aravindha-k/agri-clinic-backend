"""
Delete test/demo business data only. Never touches auth users or employee profiles.

Usage:
  python manage.py reset_test_business_data           # dry-run (default)
  python manage.py reset_test_business_data --confirm # apply
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def _is_production_env() -> bool:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if app_env in {"prod", "production", "render", "staging"}:
        return True
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = (
        "Remove visits, visit media/attachments, tracking logs, crop issues, "
        "field crops, and optional test farmers. Does NOT delete users or logins."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Apply deletions (default is dry-run).",
        )
        parser.add_argument(
            "--include-all-farmers",
            action="store_true",
            help="Also delete ALL farmer/field master rows (destructive; local dev only).",
        )
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="Allow running when APP_ENV is production (not recommended).",
        )

    def handle(self, *args, **options):
        if _is_production_env() and not options["allow_production"]:
            raise CommandError(
                "Refusing to run in production. Use --allow-production only if you "
                "understand the risk (still never deletes auth users)."
            )

        from farmers.data_audit import cleanup_visits_qs, farmers_safe_to_delete
        from farmers.helpers import e2e_test_farmer_filter
        from masters.models import (
            CropIssue,
            Farmer,
            FarmerField,
            FieldCrop,
            Recommendation,
        )
        from tracking.models import AvailabilityEvent, LocationLog, WorkDay
        from visits.models import Visit, VisitAttachment, VisitMedia

        dry_run = not options["confirm"]
        visit_qs = cleanup_visits_qs()
        safe_farmers, skipped = farmers_safe_to_delete()

        counts = {
            "visits": visit_qs.count(),
            "visit_media": VisitMedia.objects.count(),
            "visit_attachments": VisitAttachment.objects.count(),
            "crop_issues": CropIssue.objects.count(),
            "recommendations": Recommendation.objects.count(),
            "location_logs": LocationLog.objects.count(),
            "workdays": WorkDay.objects.count(),
            "availability_events": AvailabilityEvent.objects.count(),
            "field_crops": FieldCrop.objects.count(),
            "farmer_fields": FarmerField.objects.count(),
            "test_farmers": len(safe_farmers),
        }

        self.stdout.write(self.style.MIGRATE_HEADING("Reset test business data"))
        for key, value in counts.items():
            self.stdout.write(f"  {key}: {value}")
        if options["include_all_farmers"]:
            self.stdout.write(f"  all_farmers: {Farmer.objects.count()} (if --confirm)")
        if skipped:
            self.stdout.write(
                self.style.WARNING(f"  skipped ambiguous test farmers: {len(skipped)}")
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDry-run only. Re-run with --confirm to delete.")
            )
            return

        with transaction.atomic():
            visit_qs.delete()
            VisitMedia.objects.all().delete()
            VisitAttachment.objects.all().delete()
            CropIssue.objects.all().delete()
            Recommendation.objects.all().delete()
            LocationLog.objects.all().delete()
            AvailabilityEvent.objects.all().delete()
            WorkDay.objects.all().delete()
            FieldCrop.objects.all().delete()
            FarmerField.objects.all().delete()
            if options["include_all_farmers"]:
                Farmer.objects.all().delete()
            elif safe_farmers:
                Farmer.objects.filter(pk__in=[f.pk for f in safe_farmers]).delete()

        self.stdout.write(self.style.SUCCESS("Test business data cleared."))
        self.stdout.write(
            self.style.SUCCESS("Auth users and employee profiles were not modified.")
        )
