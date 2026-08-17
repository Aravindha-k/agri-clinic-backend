"""Idempotent import of crop pest masters from data/crop_pests.csv."""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from masters.models import Crop, CropProblem, ProblemCategory, ProblemMaster

DEFAULT_CSV = Path(__file__).resolve().parents[3] / "data" / "crop_pests.csv"

# Exact aliases only — no fuzzy guessing.
CROP_ALIASES = {
    "paddy": "Paddy",
    "rice": "Paddy",
    "maize": "Maize",
    "corn": "Maize",
    "bajra": "Bajra",
    "pearl millet": "Bajra",
    "groundnut": "Groundnut",
    "peanut": "Groundnut",
    "ragi": "Ragi",
    "blackgram": "Blackgram",
    "black gram": "Blackgram",
    "greengram": "Greengram",
    "green gram": "Greengram",
    "cluster bean": "Cluster Bean",
    "brinjal": "Brinjal",
    "bhendi": "Bhendi",
    "okra": "Bhendi",
    "cucumber": "Cucumber",
    "tomato": "Tomato",
    "chilli": "Chilli",
    "chili": "Chilli",
    "coconut": "Coconut",
}


def _match_crop(crop_name: str) -> Crop | None:
    name = (crop_name or "").strip()
    if not name:
        return None
    crop = Crop.objects.filter(name_en__iexact=name).first()
    if crop:
        return crop
    crop = Crop.objects.filter(name_ta__iexact=name).first()
    if crop:
        return crop
    alias = CROP_ALIASES.get(name.casefold())
    if alias:
        return Crop.objects.filter(name_en__iexact=alias).first()
    return None


def _get_or_create_pest(
    *,
    category: ProblemCategory,
    english: str,
    tamil: str,
) -> tuple[ProblemMaster, bool]:
    existing = (
        ProblemMaster.objects.filter(
            category=category,
            name__iexact=english,
        )
        .order_by("id")
        .first()
    )
    if existing:
        changed = False
        if tamil and existing.tamil_name != tamil:
            existing.tamil_name = tamil
            changed = True
        if not existing.is_active:
            existing.is_active = True
            changed = True
        if changed:
            existing.save()
        return existing, False
    return (
        ProblemMaster.objects.create(
            category=category,
            name=english,
            tamil_name=tamil,
            crop=None,
            is_active=True,
        ),
        True,
    )


class Command(BaseCommand):
    help = "Import crop pest ProblemMaster rows + CropProblem mappings from CSV."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=str, default=str(DEFAULT_CSV))
        parser.add_argument(
            "--create-missing-crops",
            action="store_true",
            help="Create Crop rows for unmatched crop names (default: report only).",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv"])
        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        category, _ = ProblemCategory.objects.get_or_create(
            code=ProblemCategory.CODE_PEST,
            defaults={
                "name": "Pest",
                "requires_problem_master": True,
                "is_active": True,
            },
        )
        # Prefer display name "Pest"
        if category.name != "Pest":
            category.name = "Pest"
            category.save(update_fields=["name", "updated_at"])

        created_problems = 0
        existing_problems = 0
        mappings_created = 0
        mappings_existing = 0
        matched_crops: set[str] = set()
        unmatched_crops: set[str] = set()
        crops_created = 0

        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        with transaction.atomic():
            for raw in rows:
                crop_name = (raw.get("Crop") or "").strip()
                english = (raw.get("English Pest Name") or "").strip()
                tamil = (raw.get("Tamil Pest Name") or "").strip()
                if not crop_name or not english:
                    continue
                if crop_name.casefold() == "crop" and "english" in english.casefold():
                    continue

                crop = _match_crop(crop_name)
                if crop is None:
                    if options["create_missing_crops"]:
                        crop = Crop.objects.create(
                            name_en=crop_name, name_ta=crop_name, is_active=True
                        )
                        crops_created += 1
                    else:
                        unmatched_crops.add(crop_name)
                        continue

                matched_crops.add(crop.name_en)
                problem, created = _get_or_create_pest(
                    category=category, english=english, tamil=tamil
                )
                if created:
                    created_problems += 1
                else:
                    existing_problems += 1

                # Mirror first mapping into legacy crop when empty.
                if problem.crop_id is None:
                    problem.crop = crop
                    problem.save(update_fields=["crop", "updated_at"])

                _, map_created = CropProblem.objects.get_or_create(
                    problem_master=problem, crop=crop
                )
                if map_created:
                    mappings_created += 1
                else:
                    mappings_existing += 1

            # Sathupatrakurai — Nutrient Deficiency, no crop mapping without confirmation.
            nutrient, _ = ProblemCategory.objects.get_or_create(
                code=ProblemCategory.CODE_NUTRIENT,
                defaults={
                    "name": "Nutrient Deficiency",
                    "requires_problem_master": True,
                    "is_active": True,
                },
            )
            if nutrient.name != "Nutrient Deficiency":
                nutrient.name = "Nutrient Deficiency"
                nutrient.save(update_fields=["name", "updated_at"])
            sathu = ProblemMaster.objects.filter(
                category=nutrient, name__iexact="Sathupatrakurai"
            ).first()
            if sathu is None:
                ProblemMaster.objects.create(
                    category=nutrient,
                    name="Sathupatrakurai",
                    tamil_name="சத்துப்பற்றாக்குறை",
                    crop=None,
                    is_active=True,
                )
            else:
                sathu.name = "Sathupatrakurai"
                sathu.tamil_name = "சத்துப்பற்றாக்குறை"
                sathu.is_active = True
                sathu.crop = None
                sathu.save()

        self.stdout.write(self.style.SUCCESS("import_crop_pests complete"))
        self.stdout.write(f"  problems_created: {created_problems}")
        self.stdout.write(f"  problems_existing: {existing_problems}")
        self.stdout.write(f"  mappings_created: {mappings_created}")
        self.stdout.write(f"  mappings_existing: {mappings_existing}")
        self.stdout.write(f"  crops_created: {crops_created}")
        self.stdout.write(f"  matched_crops ({len(matched_crops)}): {sorted(matched_crops)}")
        self.stdout.write(
            f"  unmatched_crops ({len(unmatched_crops)}): {sorted(unmatched_crops)}"
        )
        self.stdout.write(
            "  sathupatrakurai: Nutrient Deficiency, crop mapping=NONE "
            "(global via unrestricted problem; PRODUCT crop list not supplied)"
        )
