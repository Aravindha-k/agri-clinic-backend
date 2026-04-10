from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0011_alter_farmeractivity_farmer"),
    ]
    operations = [
        migrations.AddField(
            model_name="crop",
            name="name_en",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="crop",
            name="name_ta",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
    ]
