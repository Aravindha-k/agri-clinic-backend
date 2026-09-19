import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from accounts.models import EmployeeLocationAssignment  # noqa: E402
from masters.models import Village  # noqa: E402

print(f"AFTER Village={Village.objects.count()}")
print(f"AFTER EmployeeLocationAssignment={EmployeeLocationAssignment.objects.count()}")
