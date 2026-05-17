from django.core.management.base import BaseCommand

from farmers.helpers import farmers_directory_queryset
from masters.models import Farmer
from visits.submitted import submitted_visits_qs


class Command(BaseCommand):
    help = "Compare Farmer table totals vs API directory counts (read-only)."

    def handle(self, *args, **options):
        total_db = Farmer.objects.count()
        directory = farmers_directory_queryset().count()
        with_visits = (
            farmers_directory_queryset()
            .filter(visits__isnull=False)
            .distinct()
            .count()
        )
        zero_visits = directory - with_visits
        submitted = submitted_visits_qs().count()

        self.stdout.write("=== Farmer visibility audit ===")
        self.stdout.write(f"  Farmer rows in DB:           {total_db}")
        self.stdout.write(f"  API directory (all farmers): {directory}")
        self.stdout.write(f"  Farmers with any visit FK:   {with_visits}")
        self.stdout.write(f"  Farmers with zero visits:    {zero_visits}")
        self.stdout.write(f"  Submitted visits (details):  {submitted}")
        if total_db != directory:
            self.stdout.write(
                self.style.WARNING("  MISMATCH: directory count should equal DB total")
            )
        else:
            self.stdout.write(self.style.SUCCESS("  Directory matches full Farmer table"))
