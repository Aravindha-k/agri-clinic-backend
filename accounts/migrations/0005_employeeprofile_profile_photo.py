from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_employeeprofile_can_login"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeprofile",
            name="profile_photo",
            field=models.ImageField(
                blank=True, null=True, upload_to="employee_photos/%Y/%m/"
            ),
        ),
    ]
