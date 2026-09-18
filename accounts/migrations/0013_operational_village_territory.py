import django.db.models.deletion
from django.db import migrations, models


def classify_existing_assignments(apps, schema_editor):
    """
    Fail-closed classification for operational village assignments.

    A row is operational only when it already points at a Village with
    Taluk and District. Incomplete rows stay in the table as
    is_operational=False.

    Does not invent villages, expand district/taluk rows, or repair
    Village.taluk on the master table.
    """
    Assignment = apps.get_model("accounts", "EmployeeLocationAssignment")
    Village = apps.get_model("masters", "Village")
    Taluk = apps.get_model("masters", "Taluk")
    District = apps.get_model("masters", "District")

    seen_operational = set()

    for row in Assignment.objects.all().iterator():
        update_fields = ["is_operational"]
        village = (
            Village.objects.filter(pk=row.village_id).first()
            if row.village_id
            else None
        )
        taluk = None
        district = None
        if village and village.taluk_id:
            taluk = Taluk.objects.filter(pk=village.taluk_id).first()
        if taluk and taluk.district_id:
            district = District.objects.filter(pk=taluk.district_id).first()

        key = (row.employee_id, row.village_id)
        hierarchy_ok = bool(
            village
            and village.is_active
            and taluk
            and taluk.is_active
            and district
            and district.is_active
        )
        if hierarchy_ok and key not in seen_operational:
            row.is_operational = True
            if row.taluk_id != taluk.id or row.district_id != district.id:
                row.taluk_id = taluk.id
                row.district_id = district.id
                update_fields.extend(["taluk_id", "district_id"])
            seen_operational.add(key)
        else:
            row.is_operational = False
        row.save(update_fields=update_fields)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_employeelocationassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeelocationassignment",
            name="is_operational",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text=(
                    "True only for village-level rows with a valid "
                    "District→Taluk→Village hierarchy. Legacy "
                    "district-only/taluk-only rows are False."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="employeeprofile",
            name="district",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "DEPRECATED. Not used for operational territory. "
                    "Use EmployeeLocationAssignment village rows."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="employees",
                to="masters.district",
            ),
        ),
        migrations.AlterField(
            model_name="employeeprofile",
            name="village",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "DEPRECATED. Not used for operational territory. "
                    "Use EmployeeLocationAssignment village rows."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="employees",
                to="masters.village",
            ),
        ),
        migrations.RunPython(classify_existing_assignments, noop_reverse),
        migrations.AddIndex(
            model_name="employeelocationassignment",
            index=models.Index(
                fields=["employee", "is_operational", "is_active"],
                name="accounts_em_employe_op_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeelocationassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("is_operational", True), ("village__isnull", False)
                ),
                fields=("employee", "village"),
                name="uniq_employee_operational_village",
            ),
        ),
    ]
