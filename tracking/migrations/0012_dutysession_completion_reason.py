# Generated manually for Phase 3 — additive, non-destructive.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0011_active_workday_duty_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="dutysession",
            name="completion_reason",
            field=models.CharField(
                blank=True,
                help_text="MANUAL | AUTO_EXPIRED — set when duty ends.",
                max_length=32,
                null=True,
            ),
        ),
    ]
