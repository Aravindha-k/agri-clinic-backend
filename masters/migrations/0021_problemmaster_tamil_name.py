from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0020_problemcategory_code_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="problemmaster",
            name="tamil_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Tamil display name (optional).",
                max_length=255,
            ),
        ),
    ]
