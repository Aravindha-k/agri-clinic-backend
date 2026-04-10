from django.core.management.base import BaseCommand
from system_settings.models import SystemSetting
from system_settings.initial_data import DEFAULT_SETTINGS


class Command(BaseCommand):
    help = "Initialize default system settings"

    def handle(self, *args, **options):
        for item in DEFAULT_SETTINGS:
            obj, created = SystemSetting.objects.get_or_create(
                key=item["key"],
                defaults={
                    "value": item["value"],
                    "description": item["description"],
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created {item['key']}"))
            else:
                self.stdout.write(f"Exists {item['key']}")
