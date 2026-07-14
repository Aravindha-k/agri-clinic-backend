from django.db import migrations, models


def backfill_unique_legacy_crop_names(apps, schema_editor):
    Crop = apps.get_model("masters", "Crop")
    seen = set()
    for crop in Crop.objects.order_by("id"):
        base = (
            getattr(crop, "name", None)
            or getattr(crop, "name_en", None)
            or f"Crop {crop.pk}"
        )
        name = str(base).strip() or f"Crop {crop.pk}"
        if name in seen:
            name = f"{name} {crop.pk}"
        seen.add(name)
        if crop.name != name:
            crop.name = name
            crop.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0009_preload_crops"),
    ]
    operations = [
        migrations.RunPython(
            backfill_unique_legacy_crop_names,
            migrations.RunPython.noop,
        ),
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
