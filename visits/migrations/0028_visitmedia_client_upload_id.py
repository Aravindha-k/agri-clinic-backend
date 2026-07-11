# Generated manually for offline photo idempotency.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0027_visit_duty_workday_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="visitmedia",
            name="client_upload_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddConstraint(
            model_name="visitmedia",
            constraint=models.UniqueConstraint(
                condition=models.Q(("client_upload_id", ""), _negated=True),
                fields=("visit", "client_upload_id"),
                name="uniq_visit_media_client_upload_id",
            ),
        ),
    ]
