import os
from urllib.parse import urlsplit

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings  # noqa: E402
from accounts.models import EmployeeLocationAssignment, EmployeeProfile  # noqa: E402
from masters.models import Village  # noqa: E402

db_url = getattr(settings, "DATABASE_URL", "") or ""
host = (urlsplit(db_url).hostname or "").strip() or "(unset)"
app_env = (os.getenv("APP_ENV") or "").strip().lower()
print(f"APP_ENV={app_env or '(unset)'}")
print(f"DATABASE_URL host={host}")
print(f"BEFORE Village={Village.objects.count()}")
print(f"BEFORE EmployeeLocationAssignment={EmployeeLocationAssignment.objects.count()}")
print("EMPLOYEE PROFILE RESOLUTION:")
wanted = {
    "Kaviyarasan": "KAC-0003",
    "Sasikumar": "KAC-0004",
    "Sathish": "KAC-0005",
    "Selvamani": "KAC-0006",
}
for name, code in wanted.items():
    qs = EmployeeProfile.objects.select_related("user").filter(employee_id=code)
    if qs.count() != 1:
        print(f"  {name}: STOP employee_id={code} count={qs.count()}")
        continue
    p = qs.get()
    full = (p.user.get_full_name() or p.user.first_name or "").strip()
    print(
        f"  {name}: pk={p.pk} employee_id={p.employee_id} "
        f"user={p.user.username} full_name={full!r}"
    )
print("ALL EmployeeProfile codes:")
for p in EmployeeProfile.objects.select_related("user").order_by("employee_id"):
    full = (p.user.get_full_name() or p.user.first_name or "").strip()
    print(f"  {p.employee_id} pk={p.pk} name={full!r} user={p.user.username}")
