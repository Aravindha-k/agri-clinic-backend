# Field visit problem masters (part 1 — fields + seed + ProblemMaster table)

from django.db import migrations, models
import django.db.models.deletion


DEFAULT_CATEGORIES = (
    {
        "code": "pest",
        "name": "Pest",
        "description": "Pest-related field visit problems",
        "requires_problem_master": True,
    },
    {
        "code": "disease",
        "name": "Disease",
        "description": "Disease-related field visit problems",
        "requires_problem_master": True,
    },
    {
        "code": "nutrient_deficiency",
        "name": "Nutrient Deficiency",
        "description": "Nutrient deficiency problems",
        "requires_problem_master": True,
    },
    {
        "code": "others",
        "name": "Others",
        "description": "Other problems (free-text; master dropdown optional)",
        "requires_problem_master": False,
    },
)


def _assign_codes(apps):
    ProblemCategory = apps.get_model("masters", "ProblemCategory")
    for category in ProblemCategory.objects.filter(code="").order_by("id"):
        slug = category.name.strip().lower().replace(" ", "_") or f"legacy_{category.pk}"
        if ProblemCategory.objects.filter(code=slug).exclude(pk=category.pk).exists():
            slug = f"legacy_{category.pk}"
        category.code = slug
        category.save(update_fields=["code"])


def _dedupe_codes(apps):
    ProblemCategory = apps.get_model("masters", "ProblemCategory")
    seen = {}
    for category in ProblemCategory.objects.order_by("id"):
        code = (category.code or "").strip()
        if not code:
            continue
        if code in seen:
            category.code = f"{code}_{category.pk}"
            category.is_active = False
            category.save(update_fields=["code", "is_active"])
        else:
            seen[code] = category.pk


def seed_problem_categories(apps, schema_editor):
    ProblemCategory = apps.get_model("masters", "ProblemCategory")
    for row in DEFAULT_CATEGORIES:
        ProblemCategory.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "description": row["description"],
                "requires_problem_master": row["requires_problem_master"],
                "is_active": True,
            },
        )
    _assign_codes(apps)
    _dedupe_codes(apps)


def unseed_problem_categories(apps, schema_editor):
    ProblemCategory = apps.get_model("masters", "ProblemCategory")
    ProblemCategory.objects.filter(
        code__in=[r["code"] for r in DEFAULT_CATEGORIES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0018_performance_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="problemcategory",
            name="code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Stable key, e.g. pest, disease, nutrient_deficiency, others",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="problemcategory",
            name="requires_problem_master",
            field=models.BooleanField(
                default=True,
                help_text="When False (e.g. Others), problem_master dropdown is optional.",
            ),
        ),
        migrations.AddField(
            model_name="problemcategory",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RunPython(seed_problem_categories, unseed_problem_categories),
        migrations.CreateModel(
            name="ProblemMaster",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="problem_masters",
                        to="masters.problemcategory",
                    ),
                ),
                (
                    "crop",
                    models.ForeignKey(
                        blank=True,
                        help_text="Optional: limit this problem to a crop.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="problem_masters",
                        to="masters.crop",
                    ),
                ),
            ],
            options={
                "ordering": ["category__name", "name"],
            },
        ),
        migrations.AddIndex(
            model_name="problemmaster",
            index=models.Index(
                fields=["category", "is_active"], name="masters_pro_categor_a8f2c1_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="problemmaster",
            index=models.Index(
                fields=["crop", "is_active"], name="masters_pro_crop_id_91b4e2_idx"
            ),
        ),
    ]
