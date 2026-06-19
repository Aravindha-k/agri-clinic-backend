from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tracking", "0009_duty_tracking_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeelivelocation",
            name="background_tracking_enabled",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeelivelocation",
            name="gps_enabled",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeelivelocation",
            name="gps_reported_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeelivelocation",
            name="location_permission_status",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.CreateModel(
            name="EmployeeGpsState",
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
                ("gps_enabled", models.BooleanField(blank=True, null=True)),
                (
                    "location_permission_status",
                    models.CharField(blank=True, max_length=32, null=True),
                ),
                (
                    "background_tracking_enabled",
                    models.BooleanField(blank=True, null=True),
                ),
                ("reported_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gps_state",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
