"""
Populate status from is_verified, then remove is_verified.
  - is_verified=True  → status="completed"
  - is_verified=False → status="pending"   (already the default, but be explicit)
"""

from django.db import migrations


def populate_status(apps, schema_editor):
    Visit = apps.get_model("visits", "Visit")
    Visit.objects.filter(is_verified=True).update(status="completed")
    Visit.objects.filter(is_verified=False).update(status="pending")


def reverse_status(apps, schema_editor):
    Visit = apps.get_model("visits", "Visit")
    Visit.objects.filter(status="completed").update(is_verified=True)
    Visit.objects.filter(status="pending").update(is_verified=False)


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0002_visit_status_field"),
    ]

    operations = [
        migrations.RunPython(populate_status, reverse_status),
        migrations.RemoveField(
            model_name="visit",
            name="is_verified",
        ),
    ]
