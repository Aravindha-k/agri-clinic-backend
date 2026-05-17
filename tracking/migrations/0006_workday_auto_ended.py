# Generated manually — model had auto_ended but DB column was missing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0005_locationlog_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="workday",
            name="auto_ended",
            field=models.BooleanField(
                default=False,
                help_text="Whether this workday was automatically ended due to time limit",
            ),
        ),
    ]
