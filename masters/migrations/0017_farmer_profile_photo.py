from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0016_backfill_village_district"),
    ]

    operations = [
        migrations.AddField(
            model_name="farmer",
            name="profile_photo",
            field=models.ImageField(
                blank=True, null=True, upload_to="farmer_photos/%Y/%m/"
            ),
        ),
    ]
