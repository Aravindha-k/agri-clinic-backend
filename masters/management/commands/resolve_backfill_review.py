"""Resolve allowlisted BACKFILL_REVIEW_REQUIRED legacy villages (idempotent).

Only SAFE_MANUAL_MATCH rows from the Phase 1 backfill review may be updated.

Kolathur and Koralur are ACCEPTED_LEGACY_UNRESOLVED by business decision.
They are not deployment blockers and must never be guessed.

Matching is by legacy name + district + (taluk null OR already correct taluk),
not by fragile primary keys, so the command is safe across environments.

When an imported twin already owns (taluk, official_code), identity is moved onto
the farmer-linked legacy row (taluk + code). The twin's official_code is cleared
and the twin is deactivated — Farmer.village FKs are never remapped (no merge).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from masters.location_utils import normalize_village_name
from masters.models import Farmer, Taluk, Village

# Explicit allowlist from Phase 1 backfill review (do not expand without re-review).
SAFE_MANUAL_MATCHES = (
    {
        "legacy_name": "Othiyathur",
        "taluk_name": "Kandachipuram",
        "district_name": "Villupuram",
        "official_code": "142",
        "classification": "SAFE_MANUAL_MATCH",
        "reason": (
            "Exclusive exact neighbor Oduvankuppam (Kandachipuram code 144) "
            "in quarter Excel; official Kandachipuram Othiyathur code 142 is "
            "adjacent in the same taluk list. Gingee candidate had zero "
            "candidate-taluk neighbor support."
        ),
    },
    {
        "legacy_name": "Ottampattu",
        "taluk_name": "Kandachipuram",
        "district_name": "Villupuram",
        "official_code": "133",
        "classification": "SAFE_MANUAL_MATCH",
        "reason": (
            "Exclusive exact neighbor Mugaiyur (Kandachipuram code 150) in "
            "quarter Excel near Ottampattu. Gingee candidate had zero "
            "candidate-taluk neighbor support."
        ),
    },
)

ACCEPTED_LEGACY_UNRESOLVED = (
    {
        "legacy_name": "Kolathur",
        "classification": "ACCEPTED_LEGACY_UNRESOLVED",
        "reason": (
            "Business accepted legacy record. Do not assign Taluk. "
            "Farmer 579 remains taluk=NULL until edited with a full hierarchy."
        ),
    },
    {
        "legacy_name": "Koralur",
        "classification": "ACCEPTED_LEGACY_UNRESOLVED",
        "reason": (
            "Business accepted legacy record. Do not assign Taluk. "
            "Farmers 1485 and 1486 remain taluk=NULL until edited with a "
            "full hierarchy."
        ),
    },
)

# Backwards-compatible alias used by earlier tests/imports.
STILL_AMBIGUOUS = ACCEPTED_LEGACY_UNRESOLVED


def accepted_legacy_name_keys() -> set[str]:
    return {
        normalize_village_name(row["legacy_name"])
        for row in ACCEPTED_LEGACY_UNRESOLVED
    }


def find_unexpected_unresolved() -> list[dict]:
    """Ambiguous official-name collisions that are not accepted legacy.

    Historical villages with taluk=NULL and no multi-taluk official collision
    are outside this Phase 1 review and are not deployment blockers.
    """
    accepted = accepted_legacy_name_keys()
    unexpected: list[dict] = []
    qs = (
        Village.objects.filter(taluk__isnull=True)
        .annotate(farmer_count=Count("farmers"))
        .filter(farmer_count__gt=0)
        .select_related("district")
        .order_by("id")
    )
    official_by_district_name: dict[tuple[int | None, str], list[Village]] = {}
    for official in Village.objects.filter(taluk__isnull=False).select_related(
        "taluk", "district"
    ):
        key = (official.district_id, normalize_village_name(official.name))
        official_by_district_name.setdefault(key, []).append(official)

    for village in qs:
        name_cf = normalize_village_name(village.name)
        if name_cf in accepted:
            continue
        candidates = official_by_district_name.get((village.district_id, name_cf), [])
        if len(candidates) > 1:
            unexpected.append(
                {
                    "village_id": village.id,
                    "name": village.name,
                    "district": getattr(village.district, "name", None),
                    "farmer_count": village.farmer_count,
                    "candidate_taluks": [c.taluk.name for c in candidates],
                }
            )
    return unexpected


def _find_legacy_village(spec: dict) -> Village | None:
    """Prefer unlinked legacy row; fall back to already-correctly-linked row."""
    qs = Village.objects.filter(
        name__iexact=spec["legacy_name"],
        district__name__iexact=spec["district_name"],
    ).select_related("district", "taluk")
    unlinked = qs.filter(taluk__isnull=True).order_by("id").first()
    if unlinked:
        return unlinked
    return (
        qs.filter(
            taluk__name__iexact=spec["taluk_name"],
            official_code=spec["official_code"],
        )
        .order_by("id")
        .first()
    )


def _backfill_farmer_taluks(village: Village, taluk: Taluk, *, dry_run: bool) -> int:
    qs = Farmer.objects.filter(village_id=village.id, taluk__isnull=True)
    count = qs.count()
    if not dry_run and count:
        qs.update(taluk_id=taluk.id)
        Farmer.objects.filter(village_id=village.id, district__isnull=True).update(
            district_id=taluk.district_id
        )
    return count


def _release_identity_twins(
    legacy: Village,
    taluk: Taluk,
    official_code: str,
    *,
    dry_run: bool,
) -> list[int]:
    """
    Release (taluk, official_code) from imported twins onto the legacy row.

    Does not remap Farmer.village. Twins are deactivated and lose official_code
    so uniq_village_taluk_code_name can be claimed by the farmer-linked row.
    """
    name_cf = normalize_village_name(legacy.name)
    released: list[int] = []
    twins = Village.objects.filter(taluk=taluk, official_code=official_code).exclude(
        pk=legacy.pk
    )
    for twin in twins:
        if normalize_village_name(twin.name) != name_cf:
            continue
        released.append(twin.id)
        if dry_run:
            continue
        if twin.official_source and not legacy.official_source:
            legacy.official_source = twin.official_source
        if twin.firka_name and not legacy.firka_name:
            legacy.firka_name = twin.firka_name
        twin.official_code = ""
        twin.is_active = False
        twin.save(update_fields=["official_code", "is_active", "updated_at"])
    return released


def apply_safe_manual_matches(*, dry_run: bool = False) -> dict:
    report = {
        "resolved": [],
        "skipped_already_linked": [],
        "errors": [],
        "accepted_legacy_unresolved": list(ACCEPTED_LEGACY_UNRESOLVED),
        "ambiguous": list(ACCEPTED_LEGACY_UNRESOLVED),
        "unexpected_unresolved": [],
        "farmers_taluk_updated": 0,
        "twins_released": [],
    }
    for spec in SAFE_MANUAL_MATCHES:
        legacy = _find_legacy_village(spec)
        if legacy is None:
            report["errors"].append(
                f"no legacy village found for {spec['legacy_name']} / {spec['district_name']}"
            )
            continue

        taluk = (
            Taluk.objects.filter(
                name__iexact=spec["taluk_name"],
                district__name__iexact=spec["district_name"],
            )
            .select_related("district")
            .first()
        )
        if taluk is None:
            report["errors"].append(
                f"taluk not found {spec['district_name']}/{spec['taluk_name']}"
            )
            continue

        if legacy.district_id and legacy.district_id != taluk.district_id:
            report["errors"].append(
                f"district mismatch village={legacy.id} "
                f"village.district={legacy.district_id} taluk.district={taluk.district_id}"
            )
            continue

        farmers = list(Farmer.objects.filter(village_id=legacy.id).order_by("id"))
        already = (
            legacy.taluk_id == taluk.id
            and (legacy.official_code or "") == spec["official_code"]
        )

        released = _release_identity_twins(
            legacy, taluk, spec["official_code"], dry_run=dry_run
        )
        if released:
            report["twins_released"].extend(
                {"legacy_id": legacy.id, "twin_id": tid, "code": spec["official_code"]}
                for tid in released
            )

        if already:
            if not dry_run and (legacy.official_source or legacy.firka_name):
                # Persist metadata copied from twins during release.
                legacy.save(
                    update_fields=["official_source", "firka_name", "updated_at"]
                )
            updated = _backfill_farmer_taluks(legacy, taluk, dry_run=dry_run)
            report["farmers_taluk_updated"] += updated
            report["skipped_already_linked"].append(
                {
                    "village_id": legacy.id,
                    "name": legacy.name,
                    "taluk": taluk.name,
                    "farmers_taluk_updated": updated,
                    "twins_released": released,
                }
            )
            continue

        entry = {
            "village_id": legacy.id,
            "name": legacy.name,
            "taluk": taluk.name,
            "official_code": spec["official_code"],
            "farmer_ids": [f.id for f in farmers],
            "classification": spec["classification"],
            "reason": spec["reason"],
            "twins_released": released,
        }
        if not dry_run:
            legacy.taluk = taluk
            if not legacy.district_id:
                legacy.district = taluk.district
            legacy.official_code = spec["official_code"]
            legacy.save()
            updated = _backfill_farmer_taluks(legacy, taluk, dry_run=False)
            entry["farmers_taluk_updated"] = updated
            report["farmers_taluk_updated"] += updated
        else:
            entry["farmers_taluk_updated"] = sum(
                1 for f in farmers if f.taluk_id is None
            )
        report["resolved"].append(entry)

    report["unexpected_unresolved"] = find_unexpected_unresolved()
    return report


class Command(BaseCommand):
    help = (
        "Apply allowlisted SAFE_MANUAL_MATCH backfill. Accepted unresolved "
        "legacy villages (Kolathur, Koralur) are left unchanged and are not "
        "deployment blockers."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report actions without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        with transaction.atomic():
            report = apply_safe_manual_matches(dry_run=dry_run)
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.WARNING("DRY RUN") if dry_run else self.style.SUCCESS("APPLIED")
        )
        linked_now = len(report["resolved"])
        already = len(report["skipped_already_linked"])
        self.stdout.write(f"  resolved_this_run: {linked_now}")
        self.stdout.write(f"  skipped_already_linked: {already}")
        self.stdout.write(f"  resolved_safe_legacy_villages: {linked_now + already}")
        for row in report["resolved"]:
            self.stdout.write(
                f"    {row['name']} id={row['village_id']} -> {row['taluk']} "
                f"code={row['official_code']} farmers={row['farmer_ids']} "
                f"farmer_taluk_updated={row.get('farmers_taluk_updated')} "
                f"twins_released={row.get('twins_released')}"
            )
        self.stdout.write(
            f"  farmers_taluk_updated_total: {report['farmers_taluk_updated']}"
        )
        self.stdout.write(f"  twins_released_total: {len(report['twins_released'])}")
        for row in report["twins_released"]:
            self.stdout.write(
                f"    twin_id={row['twin_id']} code={row['code']} "
                f"(legacy_id={row['legacy_id']})"
            )
        self.stdout.write(
            f"  accepted_legacy_unresolved: {len(report['accepted_legacy_unresolved'])}"
        )
        for row in report["accepted_legacy_unresolved"]:
            self.stdout.write(
                f"    {row['legacy_name']}: {row['classification']} — {row['reason']}"
            )
        unexpected = report["unexpected_unresolved"]
        self.stdout.write(f"  unexpected_unresolved: {len(unexpected)}")
        for row in unexpected:
            self.stdout.write(
                f"    id={row['village_id']} name={row['name']!r} "
                f"district={row['district']} farmers={row['farmer_count']} "
                f"taluks={row.get('candidate_taluks')}"
            )
        for err in report["errors"]:
            self.stdout.write(self.style.ERROR(f"  ERROR: {err}"))

        if report["errors"]:
            raise CommandError("resolve_backfill_review failed with errors")
        if unexpected:
            raise CommandError(
                f"UNEXPECTED_UNRESOLVED_LEGACY count={len(unexpected)}"
            )
