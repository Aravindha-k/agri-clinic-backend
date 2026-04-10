"""
Add status CharField to Visit model, replacing the is_verified BooleanField.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0001_initial"),
    ]

    operations = [
        # 1. Add the new status field (default="pending")
        migrations.AddField(
            model_name="visit",
            name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("completed", "Completed")],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]
