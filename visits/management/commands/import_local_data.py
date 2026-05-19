"""Import agri_local_data.json into the configured database (e.g. Render Postgres)."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Load agri_local_data.json fixture into the active DATABASE_URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="agri_local_data.json",
            help="Fixture file path (default: agri_local_data.json)",
        )

    def handle(self, *args, **options):
        call_command("loaddata", options["input"])
        self.stdout.write(self.style.SUCCESS("Fixture import complete."))
