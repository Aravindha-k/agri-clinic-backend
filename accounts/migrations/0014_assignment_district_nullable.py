import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_operational_village_territory"),
        ("masters", "0027_village_name_ta"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeelocationassignment",
            name="district",
            field=models.ForeignKey(
                blank=True,
                help_text="DEPRECATED. Not used for operational territory.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="employee_location_assignments",
                to="masters.district",
            ),
        ),
        migrations.AlterField(
            model_name="employeelocationassignment",
            name="taluk",
            field=models.ForeignKey(
                blank=True,
                help_text="DEPRECATED. Not used for operational territory.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="employee_location_assignments",
                to="masters.taluk",
            ),
        ),
        migrations.AlterField(
            model_name="employeelocationassignment",
            name="is_operational",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text=(
                    "True only for village-level Employee ↔ Village rows. "
                    "Legacy district-only/taluk-only rows are False."
                ),
            ),
        ),
    ]
