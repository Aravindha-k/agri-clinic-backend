from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0016_visit_farmer_field_relations"),
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
                default="pending",
                max_length=20,
                null=True,
            ),
        ),
    ]
