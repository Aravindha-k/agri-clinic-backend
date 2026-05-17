from django.core.management.base import BaseCommand

from visits.submitted import get_visit_cleanup_counts


class Command(BaseCommand):
    help = "Print submitted vs incomplete visit counts (read-only DB audit)."

    def handle(self, *args, **options):
        counts = get_visit_cleanup_counts()
        self.stdout.write("=== Submitted visit audit ===")
        self.stdout.write(f"  total visits:      {counts['total_visits']}")
        self.stdout.write(f"  submitted visits:  {counts['submitted_visits']}")
        self.stdout.write(f"  incomplete visits: {counts['incomplete_visits']}")
        self.stdout.write(f"  no farmer FK:      {counts['no_farmer']}")
        self.stdout.write(f"  missing crop:      {counts['missing_crop']}")
        self.stdout.write(f"  missing GPS:       {counts['missing_gps']}")
        self.stdout.write("\nSubmitted by employee:")
        for row in counts.get("submitted_by_employee") or []:
            self.stdout.write(
                f"  employee_id={row['employee_id']} "
                f"{row['employee_username']}: {row['visit_count']}"
            )
