from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0012_add_crop_names"),
    ]
    operations = [
        migrations.AlterField(
            model_name="crop",
            name="name_en",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="crop",
            name="name_ta",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
    ]
