"""Audit problem catalog counts per crop — run: py -3 scripts/audit_problem_catalog.py"""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db.models import Count, Q

from masters.models import Crop, ProblemMaster, ProblemCategory
from masters.problem_item_utils import db_category_code


def crop_filter(crop_id):
    return Q(crop_id__isnull=True) | Q(crop_id=crop_id)


def main():
    print("=== Problem Catalog DB Audit ===\n")
    print(f"Active items total: {ProblemMaster.objects.filter(is_active=True).count()}")
    print(f"Generic (crop=null): {ProblemMaster.objects.filter(is_active=True, crop_id__isnull=True).count()}")
    print("Categories:", list(ProblemCategory.objects.filter(is_active=True).values_list("code", "name")))
    print()

    crops = ["Amla", "Banana", "Groundnut", "Paddy"]
    for name in crops:
        c = Crop.objects.filter(name_en__iexact=name).first()
        if not c:
            print(f"{name}: crop not found")
            continue
        print(f"--- {name} (crop_id={c.id}) ---")
        for api_cat in ["pest", "disease", "nutrient_issue"]:
            db_code = db_category_code(api_cat)
            with_crop = (
                ProblemMaster.objects.filter(is_active=True, category__code=db_code)
                .filter(crop_filter(c.id))
                .count()
            )
            all_cat = ProblemMaster.objects.filter(is_active=True, category__code=db_code).count()
            print(f"  {api_cat:16} with crop filter: {with_crop:3}  |  all in category: {all_cat}")
        print()

    print("Top crops by linked problem count:")
    for row in (
        ProblemMaster.objects.filter(is_active=True)
        .values("crop__name_en", "crop_id")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    ):
        print(f"  {row['crop__name_en']}: {row['n']}")


if __name__ == "__main__":
    main()
