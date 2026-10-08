# Generated manually for Phase 3B canonical import.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0027_village_name_ta"),
    ]

    operations = [
        migrations.AddField(
            model_name="problemmaster",
            name="is_canonical",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Row belongs to the canonical crop-pest-disease dataset "
                    "(created or identified by the canonical import).  Legacy "
                    "rows stay False and are never reused for canonical "
                    "mappings."
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="problemmaster",
            index=models.Index(
                fields=["category", "is_canonical"],
                name="masters_pm_canonical_idx",
            ),
        ),
    ]
