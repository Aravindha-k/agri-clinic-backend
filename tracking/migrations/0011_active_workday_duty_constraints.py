from django.db import migrations, models
import django.db.models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0010_employee_gps_state"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="workday",
            constraint=models.UniqueConstraint(
                condition=django.db.models.Q(("is_active", True)),
                fields=("user",),
                name="uniq_active_workday_per_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="dutysession",
            constraint=models.UniqueConstraint(
                condition=django.db.models.Q(("is_active", True)),
                fields=("user",),
                name="uniq_active_duty_per_user",
            ),
        ),
    ]
