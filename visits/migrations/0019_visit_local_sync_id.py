from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0018_alter_visit_status_default_completed"),
    ]

    operations = [
        migrations.AddField(
            model_name="visit",
            name="local_sync_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Client-generated id for offline sync deduplication.",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="visit",
            constraint=models.UniqueConstraint(
                condition=Q(local_sync_id__isnull=False) & ~Q(local_sync_id=""),
                fields=("employee", "local_sync_id"),
                name="uniq_visit_employee_local_sync_id",
            ),
        ),
    ]
