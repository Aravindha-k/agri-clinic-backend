from django.core.management.base import BaseCommand
from audit_logs.models import AuditLog


class Command(BaseCommand):
    help = "Clear all audit logs."

    def handle(self, *args, **options):
        count = AuditLog.objects.count()
        AuditLog.objects.all().delete()
        self.stdout.write(
            self.style.SUCCESS(f"Successfully deleted {count} audit logs.")
        )
