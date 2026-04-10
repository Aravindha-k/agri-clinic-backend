from django.core.management.base import BaseCommand
from visits.models import Visit
from collections import defaultdict


class Command(BaseCommand):
    help = "Clean duplicate farmer data"

    def handle(self, *args, **kwargs):
        farmer_map = defaultdict(list)
        visits = Visit.objects.all().order_by("farmer_phone", "-visit_date")
        for v in visits:
            farmer_map[v.farmer_phone].append(v)
        for phone, records in farmer_map.items():
            latest = records[0]
            for r in records:
                if r.farmer_name != latest.farmer_name:
                    r.farmer_name = latest.farmer_name
                    r.save()
        self.stdout.write(self.style.SUCCESS("Farmer data cleaned successfully"))
