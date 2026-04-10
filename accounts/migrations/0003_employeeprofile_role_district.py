import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_add_village_to_employee_profile"),
        ("masters", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeprofile",
            name="role",
            field=models.CharField(
                choices=[("FieldAgent", "Field Agent"), ("Supervisor", "Supervisor")],
                default="FieldAgent",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="employeeprofile",
            name="district",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="employees",
                to="masters.district",
            ),
        ),
    ]
