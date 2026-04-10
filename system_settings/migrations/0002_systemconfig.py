from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("system_settings", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "heartbeat_timeout_minutes",
                    models.IntegerField(default=5),
                ),
                (
                    "gps_accuracy_limit",
                    models.IntegerField(default=50),
                ),
                (
                    "gps_jump_limit_km",
                    models.FloatField(default=5.0),
                ),
                (
                    "tracking_stale_minutes",
                    models.IntegerField(default=10),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
            ],
            options={
                "verbose_name": "System Config",
                "verbose_name_plural": "System Config",
            },
        ),
    ]
