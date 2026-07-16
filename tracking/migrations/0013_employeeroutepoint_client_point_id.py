# Generated manually for Phase 4 GPS consolidation.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tracking", "0012_dutysession_completion_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeroutepoint",
            name="client_point_id",
            field=models.CharField(
                blank=True,
                help_text="Client-generated UUID for offline replay idempotency.",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="employeeroutepoint",
            index=models.Index(
                fields=["duty_session", "client_point_id"],
                name="tracking_em_duty_se_422a77_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeeroutepoint",
            constraint=models.UniqueConstraint(
                condition=models.Q(client_point_id__isnull=False),
                fields=("duty_session", "client_point_id"),
                name="uniq_route_point_duty_client_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeeroutepoint",
            constraint=models.CheckConstraint(
                check=models.Q(latitude__gte=-90) & models.Q(latitude__lte=90),
                name="route_point_latitude_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeeroutepoint",
            constraint=models.CheckConstraint(
                check=models.Q(longitude__gte=-180) & models.Q(longitude__lte=180),
                name="route_point_longitude_range",
            ),
        ),
    ]
