from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0025_alter_visit_land_area"),
    ]

    operations = [
        migrations.AddField(
            model_name="visit",
            name="recommendation",
            field=models.TextField(blank=True, null=True),
        ),
    ]
