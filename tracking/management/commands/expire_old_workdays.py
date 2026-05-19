from django.core.management.base import BaseCommand

from tracking.workday_utils import expire_old_workdays


class Command(BaseCommand):
    help = "Auto-end active workdays older than 9 hours (end_time = start_time + 9h)."

    def handle(self, *args, **options):
        count = expire_old_workdays()
        self.stdout.write(
            self.style.SUCCESS(f"Expired {count} active workday(s) over 9 hours.")
        )
