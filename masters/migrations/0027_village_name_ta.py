from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0026_village_identity_code_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="village",
            name="name_ta",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Tamil village name. Canonical bilingual field for operational Village.",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="village",
            name="district",
            field=models.ForeignKey(
                blank=True,
                help_text="DEPRECATED. Not used for operational location.",
                null=True,
                on_delete=models.PROTECT,
                related_name="villages",
                to="masters.district",
            ),
        ),
        migrations.AlterField(
            model_name="village",
            name="taluk",
            field=models.ForeignKey(
                blank=True,
                help_text="DEPRECATED. Not used for operational location.",
                null=True,
                on_delete=models.PROTECT,
                related_name="villages",
                to="masters.taluk",
            ),
        ),
        migrations.AlterField(
            model_name="village",
            name="firka_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="DEPRECATED. Not used for operational location.",
                max_length=255,
            ),
        ),
    ]
