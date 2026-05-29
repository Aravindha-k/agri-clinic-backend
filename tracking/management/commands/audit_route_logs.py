from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from accounts.models import EmployeeProfile
from tracking.models import LocationLog, WorkDay


class Command(BaseCommand):
    help = "Audit GPS route logs for an employee on a given date."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument(
            "--date",
            type=str,
            help="YYYY-MM-DD (default: today)",
        )

    def handle(self, *args, **options):
        user_id = options["user_id"]
        date_str = options.get("date")
        target_date = parse_date(date_str) if date_str else datetime.now().date()

        emp = EmployeeProfile.objects.filter(user_id=user_id).first()
        employee_id = emp.employee_id if emp else "(no profile)"

        workday_count = WorkDay.objects.filter(
            user_id=user_id, date=target_date
        ).count()
        logs = LocationLog.objects.filter(
            user_id=user_id, recorded_at__date=target_date
        ).order_by("recorded_at")
        log_count = logs.count()
        first = logs.first()
        last = logs.last()

        self.stdout.write(f"employee_id={employee_id}")
        self.stdout.write(f"user_id={user_id}")
        self.stdout.write(f"date={target_date}")
        self.stdout.write(f"workday_count={workday_count}")
        self.stdout.write(f"location_log_count={log_count}")
        if first:
            self.stdout.write(
                f"first_point=({first.latitude},{first.longitude}) @ {first.recorded_at}"
            )
        else:
            self.stdout.write("first_point=(none)")
        if last:
            self.stdout.write(
                f"last_point=({last.latitude},{last.longitude}) @ {last.recorded_at}"
            )
        else:
            self.stdout.write("last_point=(none)")
