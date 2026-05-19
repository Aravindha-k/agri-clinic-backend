"""Export local DB to agri_local_data.json (UTF-8 safe on Windows)."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Dump local data to agri_local_data.json for Render import."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="agri_local_data.json",
            help="Fixture file path (default: agri_local_data.json)",
        )

    def handle(self, *args, **options):
        output = options["output"]
        with open(output, "w", encoding="utf-8") as handle:
            call_command(
                "dumpdata",
                natural_foreign=True,
                natural_primary=True,
                exclude=["contenttypes", "auth.permission", "sessions"],
                indent=2,
                stdout=handle,
            )
        self.stdout.write(self.style.SUCCESS(f"Exported fixture to {output}"))
