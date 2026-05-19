from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_employeeprofile_profile_photo"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeprofile",
            name="profile_photo_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
