"""Fix accounts migration drift: 0007 marked applied but table missing."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.core.management import call_command
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute(
        "DELETE FROM django_migrations WHERE app = %s AND name = %s",
        ["accounts", "0007_employeedevicesession"],
    )
    print(f"Removed stale migration row(s): {cursor.rowcount}")

call_command("migrate", "accounts", verbosity=2)
call_command("migrate", verbosity=1)
print("Done.")
