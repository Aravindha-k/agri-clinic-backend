# Generated manually for field visit architecture

from django.db import migrations, models
import django.db.models.deletion


def backfill_problem_description(apps, schema_editor):
    Visit = apps.get_model("visits", "Visit")
    for visit in Visit.objects.filter(problem_description__isnull=True).exclude(
        problem_seen=""
    ).exclude(problem_seen__isnull=True):
        visit.problem_description = visit.problem_seen
        visit.save(update_fields=["problem_description"])


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0019_field_visit_problem_masters"),
        ("visits", "0023_visit_observation_field_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="visit",
            name="farmer_age",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Farmer age at time of visit (field visit form).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="visit",
            name="problem_category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="visits",
                to="masters.problemcategory",
            ),
        ),
        migrations.AddField(
            model_name="visit",
            name="problem_master",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="visits",
                to="masters.problemmaster",
            ),
        ),
        migrations.AddField(
            model_name="visit",
            name="problem_description",
            field=models.TextField(
                blank=True,
                help_text="Required narrative for field visit submit.",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_problem_description, migrations.RunPython.noop),
    ]
