"""Idempotent import of official business location masters from CSV."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from masters.location_utils import normalize_village_name, village_identity_key
from masters.management.commands.resolve_backfill_review import (
    accepted_legacy_name_keys,
)
from masters.models import District, Farmer, Taluk, Village

DEFAULT_CSV = Path(__file__).resolve().parents[3] / "data" / "business_locations.csv"

EXPECTED_DISTRICTS = {"Villupuram", "Tiruvannamalai", "Cuddalore"}
EXPECTED_TALUKS = {
    ("Villupuram", "Villupuram"),
    ("Villupuram", "Kandachipuram"),
    ("Villupuram", "Vikkiravandi"),
    ("Villupuram", "Tindivanam"),
    ("Villupuram", "Gingee"),
    ("Villupuram", "Melmalaiyanur"),
    ("Villupuram", "Vanur"),
    ("Villupuram", "Marakkanam"),
    ("Tiruvannamalai", "Tiruvannamalai"),
    ("Cuddalore", "Cuddalore"),
    ("Cuddalore", "Panruti"),
}

MELMALAIYANUR_META = {
    "summary_count": 80,
    "detailed_pdf_count": 81,
    "imported": 81,
    "status": "OFFICIAL_SOURCE_COUNT_MISMATCH",
}


def _get_or_create_district(name: str) -> tuple[District, bool]:
    existing = District.objects.filter(name__iexact=name).first()
    if existing:
        return existing, False
    return District.objects.create(name=name, is_active=True), True


def _get_or_create_taluk(district: District, name: str) -> tuple[Taluk, bool]:
    existing = Taluk.objects.filter(district=district, name__iexact=name).first()
    if existing:
        return existing, False
    return Taluk.objects.create(district=district, name=name, is_active=True), True


def _find_village_for_identity(
    *,
    taluk: Taluk,
    official_code: str,
    name: str,
) -> Village | None:
    code = (official_code or "").strip()
    name_cf = normalize_village_name(name)
    qs = Village.objects.filter(taluk=taluk)
    if code:
        for village in qs.filter(official_code=code):
            if normalize_village_name(village.name) == name_cf:
                return village
        return None
    for village in qs.filter(official_code=""):
        if normalize_village_name(village.name) == name_cf:
            return village
    return None


def _backfill_existing_villages(report: dict) -> None:
    """
    Attach taluk to existing villages when an unambiguous official match exists.
    Ambiguous cases are reported; never guessed.
    """
    review: list[str] = []
    linked = 0
    accepted = accepted_legacy_name_keys()
    for village in Village.objects.filter(taluk__isnull=True).select_related("district"):
        name_cf = normalize_village_name(village.name)
        if not name_cf:
            continue
        if name_cf in accepted:
            # Business-accepted legacy rows: never guess or remap.
            continue
        candidates = list(
            Village.objects.filter(taluk__isnull=False)
            .select_related("taluk", "district")
            .filter(name__iexact=village.name)
        )
        # Also match by normalized name within same district if district known.
        if not candidates and village.district_id:
            candidates = [
                v
                for v in Village.objects.filter(
                    taluk__isnull=False, district_id=village.district_id
                ).select_related("taluk")
                if normalize_village_name(v.name) == name_cf
            ]
        # Prefer linking the *legacy* row itself to a taluk when official row
        # with same name exists under one taluk in the same district.
        official_same_district = []
        if village.district_id:
            official_same_district = [
                v
                for v in Village.objects.filter(
                    taluk__isnull=False,
                    district_id=village.district_id,
                ).exclude(pk=village.pk)
                if normalize_village_name(v.name) == name_cf
            ]
        if len(official_same_district) == 1:
            match = official_same_district[0]
            # Re-point farmers from legacy village to official if different rows.
            if match.pk != village.pk:
                Farmer.objects.filter(village_id=village.pk).update(village_id=match.pk)
                # Deactivate unused legacy duplicate (never delete).
                if not Farmer.objects.filter(village_id=village.pk).exists():
                    village.is_active = False
                    village.save(update_fields=["is_active", "updated_at"])
                linked += 1
            else:
                village.taluk = match.taluk
                village.district = match.district
                if match.official_code and not village.official_code:
                    village.official_code = match.official_code
                village.save()
                linked += 1
            continue
        if len(official_same_district) > 1:
            review.append(
                f"BACKFILL_REVIEW_REQUIRED village_id={village.pk} "
                f"name={village.name!r} district={getattr(village.district, 'name', None)} "
                f"candidates={[c.taluk.name for c in official_same_district]}"
            )
            continue
        # No district: try statewide unique name among official rows.
        statewide = [
            v
            for v in Village.objects.filter(taluk__isnull=False).select_related("taluk")
            if normalize_village_name(v.name) == name_cf
        ]
        if len(statewide) == 1:
            match = statewide[0]
            if match.pk != village.pk:
                Farmer.objects.filter(village_id=village.pk).update(village_id=match.pk)
                if not Farmer.objects.filter(village_id=village.pk).exists():
                    village.is_active = False
                    village.save(update_fields=["is_active", "updated_at"])
            else:
                village.taluk = match.taluk
                village.district_id = match.district_id
                village.save()
            linked += 1
        elif len(statewide) > 1:
            review.append(
                f"BACKFILL_REVIEW_REQUIRED village_id={village.pk} "
                f"name={village.name!r} candidates="
                f"{[(c.district.name if c.district_id else None, c.taluk.name) for c in statewide]}"
            )
    report["backfill_linked"] = linked
    report["backfill_review"] = review


class Command(BaseCommand):
    help = "Import official business location masters (district/taluk/village)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default=str(DEFAULT_CSV),
            help="Path to business_locations.csv",
        )
        parser.add_argument(
            "--skip-backfill",
            action="store_true",
            help="Skip legacy village backfill pass.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv"])
        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        report = {
            "districts_created": 0,
            "districts_existing": 0,
            "taluks_created": 0,
            "taluks_existing": 0,
            "villages_created": 0,
            "villages_existing": 0,
            "villages_updated": 0,
            "skipped_invalid": 0,
            "per_taluk": {},
            "mismatches": [],
            "melmalaiyanur": MELMALAIYANUR_META,
        }

        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            raise CommandError("CSV is empty.")

        with transaction.atomic():
            district_cache: dict[str, District] = {}
            taluk_cache: dict[tuple[int, str], Taluk] = {}
            seen_identity: set[str] = set()
            taluk_counts: dict[str, int] = defaultdict(int)

            for raw in rows:
                state = (raw.get("state_name") or "").strip()
                district_name = (raw.get("district_name") or "").strip()
                taluk_name = (raw.get("taluk_name") or "").strip()
                village_name = (raw.get("village_name") or "").strip()
                official_code = (raw.get("official_code") or "").strip()
                official_source = (raw.get("official_source") or "").strip()
                firka_name = (raw.get("firka_name") or "").strip()
                is_active = (raw.get("is_active") or "true").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                }

                if not district_name or not taluk_name or not village_name:
                    report["skipped_invalid"] += 1
                    continue
                if district_name not in EXPECTED_DISTRICTS:
                    report["skipped_invalid"] += 1
                    continue
                if (district_name, taluk_name) not in EXPECTED_TALUKS:
                    report["skipped_invalid"] += 1
                    continue

                if district_name not in district_cache:
                    district, created = _get_or_create_district(district_name)
                    district_cache[district_name] = district
                    if created:
                        report["districts_created"] += 1
                    else:
                        report["districts_existing"] += 1
                district = district_cache[district_name]

                tkey = (district.pk, taluk_name.casefold())
                if tkey not in taluk_cache:
                    taluk, created = _get_or_create_taluk(district, taluk_name)
                    taluk_cache[tkey] = taluk
                    if created:
                        report["taluks_created"] += 1
                    else:
                        report["taluks_existing"] += 1
                taluk = taluk_cache[tkey]

                identity = village_identity_key(
                    taluk_id=taluk.pk,
                    official_code=official_code,
                    name=village_name,
                )
                if identity in seen_identity:
                    # Same official identity twice in CSV — keep first.
                    continue
                seen_identity.add(identity)

                village = _find_village_for_identity(
                    taluk=taluk,
                    official_code=official_code,
                    name=village_name,
                )
                if village is None:
                    Village.objects.create(
                        name=village_name,
                        district=district,
                        taluk=taluk,
                        official_code=official_code,
                        official_source=official_source,
                        firka_name=firka_name,
                        is_active=is_active,
                    )
                    report["villages_created"] += 1
                else:
                    changed = False
                    for attr, value in (
                        ("name", village_name),
                        ("district", district),
                        ("taluk", taluk),
                        ("official_code", official_code or village.official_code),
                        ("official_source", official_source or village.official_source),
                        ("firka_name", firka_name or village.firka_name),
                        ("is_active", is_active),
                    ):
                        if getattr(village, attr) != value:
                            setattr(village, attr, value)
                            changed = True
                    if changed:
                        village.save()
                        report["villages_updated"] += 1
                    else:
                        report["villages_existing"] += 1

                taluk_counts[f"{district_name}/{taluk_name}"] += 1

            report["per_taluk"] = dict(sorted(taluk_counts.items()))
            report["districts_total"] = District.objects.filter(
                name__in=EXPECTED_DISTRICTS
            ).count()
            report["taluks_total"] = Taluk.objects.filter(
                district__name__in=EXPECTED_DISTRICTS,
                name__in={t for _, t in EXPECTED_TALUKS},
            ).count()
            report["villages_total_business"] = Village.objects.filter(
                taluk__isnull=False,
                taluk__district__name__in=EXPECTED_DISTRICTS,
            ).count()

            mel_count = Village.objects.filter(
                taluk__name__iexact="Melmalaiyanur",
                taluk__district__name__iexact="Villupuram",
                is_active=True,
            ).count()
            report["melmalaiyanur"] = {
                **MELMALAIYANUR_META,
                "imported": mel_count,
            }
            if mel_count != 81:
                report["mismatches"].append(
                    f"Melmalaiyanur expected 81 detailed PDF rows, got {mel_count}"
                )

            if not options["skip_backfill"]:
                _backfill_existing_villages(report)

        self.stdout.write(self.style.SUCCESS("import_business_locations complete"))
        for key in (
            "districts_created",
            "districts_existing",
            "taluks_created",
            "taluks_existing",
            "villages_created",
            "villages_existing",
            "villages_updated",
            "skipped_invalid",
            "districts_total",
            "taluks_total",
            "villages_total_business",
            "backfill_linked",
        ):
            if key in report:
                self.stdout.write(f"  {key}: {report[key]}")
        self.stdout.write(f"  melmalaiyanur: {report['melmalaiyanur']}")
        if report.get("backfill_review"):
            self.stdout.write(self.style.WARNING("  BACKFILL_REVIEW_REQUIRED:"))
            for line in report["backfill_review"][:50]:
                self.stdout.write(f"    {line}")
            if len(report["backfill_review"]) > 50:
                self.stdout.write(
                    f"    ... and {len(report['backfill_review']) - 50} more"
                )
        for label, count in report["per_taluk"].items():
            self.stdout.write(f"  {label}: {count}")
        return ""
