from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0022_rename_masters_pro_categor_a8f2c1_idx_masters_pro_categor_8de110_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="farmer",
            name="source_file",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="farmer",
            name="source_quarter",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="farmer",
            name="state",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AlterField(
            model_name="farmer",
            name="phone",
            field=models.CharField(blank=True, default="", max_length=15),
        ),
    ]
