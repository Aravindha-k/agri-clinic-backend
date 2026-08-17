"""Read-only village classification and Admin location-count helpers.

Does not mutate Village/Farmer rows. Duplicate same-name villages with
different official codes are distinct identities, not merge candidates.
"""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q

from masters.location_utils import normalize_village_name
from masters.management.commands.resolve_backfill_review import accepted_legacy_name_keys
from masters.models import District, Farmer, Taluk, Village

CLASS_OFFICIAL_IMPORTED = "OFFICIAL_IMPORTED"
CLASS_LEGACY_LINKED = "LEGACY_LINKED"
CLASS_LEGACY_UNLINKED = "LEGACY_UNLINKED"
CLASS_ACCEPTED_LEGACY_UNRESOLVED = "ACCEPTED_LEGACY_UNRESOLVED"
CLASS_INACTIVE_IMPORT_TWIN = "INACTIVE_IMPORT_TWIN"
CLASS_OTHER = "OTHER"

CLASS_ORDER = (
    CLASS_OFFICIAL_IMPORTED,
    CLASS_LEGACY_LINKED,
    CLASS_LEGACY_UNLINKED,
    CLASS_ACCEPTED_LEGACY_UNRESOLVED,
    CLASS_INACTIVE_IMPORT_TWIN,
    CLASS_OTHER,
)

BUSINESS_DISTRICT_NAMES = ("Villupuram", "Tiruvannamalai", "Cuddalore")


def _has_official_identity(village: Village) -> bool:
    return bool((village.official_code or "").strip()) or bool(
        (village.official_source or "").strip()
    )


def inactive_import_twin_ids() -> set[int]:
    """Inactive rows whose (taluk, name) official identity is held by another row."""
    holders: dict[tuple[int, str], list[int]] = defaultdict(list)
    for v in Village.objects.filter(taluk__isnull=False).exclude(official_code=""):
        holders[(v.taluk_id, normalize_village_name(v.name))].append(v.id)
    twins = set()
    for v in Village.objects.filter(
        is_active=False, taluk__isnull=False, official_code=""
    ).only("id", "name", "taluk_id"):
        if holders.get((v.taluk_id, normalize_village_name(v.name))):
            twins.add(v.id)
    return twins


def classify_village(
    village: Village,
    *,
    farmer_count: int = 0,
    twin_ids: set[int] | None = None,
    accepted: set[str] | None = None,
) -> str:
    twin_ids = twin_ids if twin_ids is not None else set()
    accepted = accepted if accepted is not None else accepted_legacy_name_keys()
    name_cf = normalize_village_name(village.name)
    if village.taluk_id is None and name_cf in accepted:
        return CLASS_ACCEPTED_LEGACY_UNRESOLVED
    if village.id in twin_ids:
        return CLASS_INACTIVE_IMPORT_TWIN
    if village.taluk_id and _has_official_identity(village):
        return CLASS_OFFICIAL_IMPORTED
    if farmer_count > 0:
        return CLASS_LEGACY_LINKED
    if village.taluk_id is None:
        return CLASS_LEGACY_UNLINKED
    return CLASS_OTHER


def farmer_counts_by_village() -> dict[int, int]:
    return dict(
        Farmer.objects.exclude(village_id=None)
        .values("village_id")
        .annotate(c=Count("id"))
        .values_list("village_id", "c")
    )


def classify_all_villages() -> dict[str, list[Village]]:
    accepted = accepted_legacy_name_keys()
    twin_ids = inactive_import_twin_ids()
    farmers = farmer_counts_by_village()
    buckets: dict[str, list[Village]] = {key: [] for key in CLASS_ORDER}
    for village in Village.objects.select_related("district", "taluk").iterator():
        label = classify_village(
            village,
            farmer_count=farmers.get(village.id, 0),
            twin_ids=twin_ids,
            accepted=accepted,
        )
        buckets[label].append(village)
    return buckets


def reconcile_village_counts(buckets: dict[str, list] | None = None) -> dict:
    """Exclusive class counts that must sum to Village.objects.count()."""
    if buckets is None:
        buckets = classify_all_villages()
    classes = {key: len(buckets.get(key, [])) for key in CLASS_ORDER}
    total = Village.objects.count()
    classified = sum(classes.values())
    return {
        "total": total,
        "active": Village.objects.filter(is_active=True).count(),
        "inactive": Village.objects.filter(is_active=False).count(),
        "classes": classes,
        "legacy_preserved": classes[CLASS_LEGACY_LINKED]
        + classes[CLASS_LEGACY_UNLINKED],
        "classified_sum": classified,
        "reconciles": classified == total,
    }


def location_master_counts() -> dict:
    """Canonical Admin badge counts: ACTIVE selectable records."""
    return {
        "count_basis": "active",
        "districts": {
            "total": District.objects.count(),
            "active": District.objects.filter(is_active=True).count(),
        },
        "taluks": {
            "total": Taluk.objects.count(),
            "active": Taluk.objects.filter(is_active=True).count(),
        },
        "villages": {
            "total": Village.objects.count(),
            "active": Village.objects.filter(is_active=True).count(),
            "official_imported_active": Village.objects.filter(
                is_active=True, taluk__isnull=False
            ).count(),
            "legacy_taluk_null_active": Village.objects.filter(
                is_active=True, taluk__isnull=True
            ).count(),
        },
    }


def village_count_annotation():
    return Count("villages", filter=Q(villages__is_active=True))
