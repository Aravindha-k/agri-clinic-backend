"""Prune district/village masters to only locations used by live farmer records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.db.models import Count, Q

from masters.models import District, Farmer, Village


@dataclass
class LocationCleanupPlan:
    total_districts: int = 0
    total_villages: int = 0
    districts_to_keep: list[dict[str, Any]] = field(default_factory=list)
    villages_to_keep: list[dict[str, Any]] = field(default_factory=list)
    districts_to_remove: list[dict[str, Any]] = field(default_factory=list)
    villages_to_remove: list[dict[str, Any]] = field(default_factory=list)
    farmers_without_village: int = 0
    farmers_without_district: int = 0
    villages_without_district: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_districts": self.total_districts,
            "total_villages": self.total_villages,
            "districts_to_keep_count": len(self.districts_to_keep),
            "villages_to_keep_count": len(self.villages_to_keep),
            "districts_to_remove_count": len(self.districts_to_remove),
            "villages_to_remove_count": len(self.villages_to_remove),
            "districts_to_remove": self.districts_to_remove,
            "villages_to_remove": self.villages_to_remove,
            "farmers_without_village": self.farmers_without_village,
            "farmers_without_district": self.farmers_without_district,
            "villages_without_district": self.villages_without_district,
        }


def build_location_cleanup_plan() -> LocationCleanupPlan:
    """Compute which location masters are used by farmers vs safe to delete."""
    plan = LocationCleanupPlan()
    plan.total_districts = District.objects.count()
    plan.total_villages = Village.objects.count()

    farmer_village_ids = set(
        Farmer.objects.exclude(village_id__isnull=True).values_list(
            "village_id", flat=True
        )
    )
    farmer_district_ids = set(
        Farmer.objects.exclude(district_id__isnull=True).values_list(
            "district_id", flat=True
        )
    )

    kept_villages = Village.objects.filter(id__in=farmer_village_ids)
    village_district_ids = set(
        kept_villages.exclude(district_id__isnull=True).values_list(
            "district_id", flat=True
        )
    )
    district_keep_ids = farmer_district_ids | village_district_ids

    plan.districts_to_keep = list(
        District.objects.filter(id__in=district_keep_ids)
        .order_by("name")
        .values("id", "name")
    )
    plan.villages_to_keep = list(
        kept_villages.order_by("name").values("id", "name", "district_id")
    )
    plan.districts_to_remove = list(
        District.objects.exclude(id__in=district_keep_ids)
        .order_by("name")
        .values("id", "name")
    )
    plan.villages_to_remove = list(
        Village.objects.exclude(id__in=farmer_village_ids)
        .order_by("name")
        .values("id", "name", "district_id")
    )

    plan.farmers_without_village = Farmer.objects.filter(village_id__isnull=True).count()
    plan.farmers_without_district = Farmer.objects.filter(
        district_id__isnull=True
    ).count()
    plan.villages_without_district = kept_villages.filter(
        district_id__isnull=True
    ).count()

    return plan


def verify_farmer_locations() -> dict[str, Any]:
    """Post-cleanup integrity checks."""
    farmer_count = Farmer.objects.count()
    missing_village = Farmer.objects.filter(village_id__isnull=True).count()
    missing_district = Farmer.objects.filter(district_id__isnull=True).count()

    invalid_village_fk = (
        Farmer.objects.filter(village_id__isnull=False)
        .exclude(village_id__in=Village.objects.values("id"))
        .count()
    )
    invalid_district_fk = (
        Farmer.objects.filter(district_id__isnull=False)
        .exclude(district_id__in=District.objects.values("id"))
        .count()
    )
    villages_missing_district = Village.objects.filter(
        id__in=Farmer.objects.exclude(village_id__isnull=True).values("village_id"),
        district_id__isnull=True,
    ).count()

    return {
        "farmer_count": farmer_count,
        "district_count": District.objects.count(),
        "village_count": Village.objects.count(),
        "farmers_missing_village": missing_village,
        "farmers_missing_district": missing_district,
        "farmers_invalid_village_fk": invalid_village_fk,
        "farmers_invalid_district_fk": invalid_district_fk,
        "farmer_villages_missing_district": villages_missing_district,
        "ok": (
            invalid_village_fk == 0
            and invalid_district_fk == 0
            and villages_missing_district == 0
        ),
    }


def execute_location_cleanup(plan: LocationCleanupPlan) -> dict[str, int]:
    """Delete orphan villages then orphan districts (FK-safe order)."""
    village_ids = [row["id"] for row in plan.villages_to_remove]
    district_ids = [row["id"] for row in plan.districts_to_remove]

    deleted: dict[str, int] = {}
    with transaction.atomic():
        deleted["masters_village"], _ = Village.objects.filter(
            id__in=village_ids
        ).delete()
        deleted["masters_district"], _ = District.objects.filter(
            id__in=district_ids
        ).delete()

    return deleted


def farmer_location_summary() -> dict[str, Any]:
    """Districts/villages referenced by imported farmers."""
    used_districts = list(
        District.objects.filter(farmers__isnull=False)
        .annotate(farmer_count=Count("farmers", distinct=True))
        .order_by("name")
        .values("id", "name", "farmer_count")
    )
    used_villages = list(
        Village.objects.filter(farmers__isnull=False)
        .annotate(farmer_count=Count("farmers", distinct=True))
        .order_by("name")
        .values("id", "name", "district_id", "farmer_count")
    )
    return {
        "farmer_count": Farmer.objects.count(),
        "districts_used": used_districts,
        "villages_used_count": len(used_villages),
        "districts_used_count": len(used_districts),
    }
