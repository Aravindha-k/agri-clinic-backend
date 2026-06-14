from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0023_farmer_import_source_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="farmer",
            name="source_quarter",
            field=models.CharField(
                blank=True,
                default="",
                help_text="One or more quarter keys, e.g. quarter1,quarter3",
                max_length=100,
            ),
        ),
    ]
