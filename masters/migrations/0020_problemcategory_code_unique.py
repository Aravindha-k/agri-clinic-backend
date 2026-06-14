from django.db import migrations, models


def dedupe_codes(apps, schema_editor):
    ProblemCategory = apps.get_model("masters", "ProblemCategory")
    seen = {}
    for category in ProblemCategory.objects.order_by("id"):
        code = (category.code or "").strip()
        if not code:
            slug = category.name.strip().lower().replace(" ", "_") or f"legacy_{category.pk}"
            category.code = slug
            code = slug
        if code in seen:
            category.code = f"{code}_{category.pk}"
            category.is_active = False
        else:
            seen[code] = category.pk
        category.save(update_fields=["code", "is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0019_field_visit_problem_masters"),
    ]

    operations = [
        migrations.RunPython(dedupe_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="problemcategory",
            name="code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Stable key, e.g. pest, disease, nutrient_deficiency, others",
                max_length=40,
                unique=True,
            ),
        ),
    ]
