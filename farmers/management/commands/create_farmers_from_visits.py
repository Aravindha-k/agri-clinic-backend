"""
MIGRATION STRATEGY — Farmer-Centric Re-Architecture
=====================================================

This migration maps existing Visit records (which have farmer_name as a
CharField) to the new Farmer FK.

Run AFTER `makemigrations` has created the schema migration:

    python manage.py makemigrations masters visits farmers
    python manage.py migrate
    python manage.py create_farmers_from_visits     ← this command

The management command:
1. Finds all unique (farmer_name, village) pairs in Visit.
2. Creates Farmer records where no matching Farmer exists.
3. Backfills Visit.farmer FK from farmer_name + village match.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from visits.models import Visit
from masters.models import Farmer


class Command(BaseCommand):
    help = "Backfill Visit.farmer FK from existing farmer_name data"

    def handle(self, *args, **options):
        visits_without_farmer = Visit.objects.filter(farmer__isnull=True).exclude(
            farmer_name=""
        )
        total = visits_without_farmer.count()
        self.stdout.write(f"Found {total} visits without farmer FK")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to migrate."))
            return

        # Group by (farmer_name, village_id)
        pairs = (
            visits_without_farmer.values_list("farmer_name", "village_id")
            .distinct()
            .order_by("farmer_name")
        )

        created = 0
        matched = 0

        with transaction.atomic():
            for farmer_name, village_id in pairs:
                # Try to find existing farmer
                farmer = Farmer.objects.filter(
                    name__iexact=farmer_name,
                    village_id=village_id,
                ).first()

                if not farmer:
                    # Create a new Farmer record
                    farmer = Farmer.objects.create(
                        name=farmer_name,
                        phone="",
                        village_id=village_id,
                    )
                    created += 1
                else:
                    matched += 1

                # Backfill all visits with this name+village
                Visit.objects.filter(
                    farmer_name=farmer_name,
                    village_id=village_id,
                    farmer__isnull=True,
                ).update(farmer=farmer)

        linked = (
            total
            - Visit.objects.filter(farmer__isnull=True).exclude(farmer_name="").count()
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Created {created} farmers, matched {matched} existing. "
                f"Linked {linked} visits."
            )
        )
