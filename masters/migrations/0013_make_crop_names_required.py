from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0009_preload_crops"),
    ]
    operations = [
        migrations.AlterField(
            model_name="crop",
            name="name_en",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="crop",
            name="name_ta",
            field=models.CharField(max_length=255),
        ),
    ]
