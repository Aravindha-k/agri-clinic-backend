from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0017_alter_visit_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="visit",
            name="status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("active", "Active"),
                    ("completed", "Completed"),
                    ("pending", "Pending"),
                ],
                default="completed",
                max_length=20,
                null=True,
            ),
        ),
    ]
