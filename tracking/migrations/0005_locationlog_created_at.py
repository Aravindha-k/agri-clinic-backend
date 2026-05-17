# Generated manually for production GPS audit trail

from django.db import migrations, models
from django.db.models import F


def backfill_created_at(apps, schema_editor):
    LocationLog = apps.get_model("tracking", "LocationLog")
    LocationLog.objects.filter(created_at__isnull=True).update(created_at=F("recorded_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0004_workday_latitude_workday_longitude"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationlog",
            name="created_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.RunPython(backfill_created_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="locationlog",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                help_text="Server time when this point was stored",
            ),
        ),
    ]
