from django.db import migrations, models
import django.db.models.deletion


def link_existing_visits(apps, schema_editor):
    Visit = apps.get_model("visits", "Visit")
    Farmer = apps.get_model("masters", "Farmer")
    FarmerField = apps.get_model("masters", "FarmerField")

    for visit in Visit.objects.filter(farmer__isnull=True).iterator():
        farmer = None
        phone = (visit.farmer_phone or "").strip()
        name = (visit.farmer_name or "").strip()

        if phone:
            farmer = Farmer.objects.filter(phone=phone).order_by("id").first()
        if farmer is None and name:
            farmer = Farmer.objects.filter(name__iexact=name).order_by("id").first()
        if farmer is None:
            continue

        updates = ["farmer"]
        visit.farmer = farmer

        if not visit.farmer_name:
            visit.farmer_name = farmer.name
            updates.append("farmer_name")
        if not visit.farmer_phone:
            visit.farmer_phone = farmer.phone
            updates.append("farmer_phone")

        field = None
        land_name = (visit.land_name or "").strip()
        if land_name:
            field = (
                FarmerField.objects.filter(farmer=farmer, land_name__iexact=land_name)
                .order_by("id")
                .first()
            )
        if field is None:
            field = FarmerField.objects.filter(farmer=farmer).order_by("id").first()
        if field is not None:
            visit.field = field
            updates.append("field")
            if not visit.land_name:
                visit.land_name = field.land_name
                updates.append("land_name")
            if visit.land_area is None and field.land_size is not None:
                visit.land_area = float(field.land_size)
                updates.append("land_area")

        visit.save(update_fields=updates)


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0014_alter_crop_options_remove_crop_name"),
        ("visits", "0015_add_caption_to_visitmedia"),
    ]

    operations = [
        migrations.AddField(
            model_name="visit",
            name="farmer",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="visits",
                to="masters.farmer",
            ),
        ),
        migrations.AddField(
            model_name="visit",
            name="field",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="visits",
                to="masters.farmerfield",
            ),
        ),
        migrations.RunPython(link_existing_visits, migrations.RunPython.noop),
    ]
