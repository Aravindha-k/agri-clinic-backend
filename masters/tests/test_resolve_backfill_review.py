"""Tests for allowlisted legacy village backfill review resolution."""

from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from masters.management.commands.resolve_backfill_review import (
    ACCEPTED_LEGACY_UNRESOLVED,
    apply_safe_manual_matches,
)
from masters.models import District, Farmer, Taluk, Village


class ResolveBackfillReviewTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name="Villupuram")
        self.kanda = Taluk.objects.create(name="Kandachipuram", district=self.district)
        self.gingee = Taluk.objects.create(name="Gingee", district=self.district)
        self.vikki = Taluk.objects.create(name="Vikkiravandi", district=self.district)
        self.tindi = Taluk.objects.create(name="Tindivanam", district=self.district)
        self.villupuram_taluk = Taluk.objects.create(
            name="Villupuram", district=self.district
        )
        self.marakkanam = Taluk.objects.create(name="Marakkanam", district=self.district)

        # Official twins (imported masters) — must not become Farmer FK targets.
        self.twin_othiyathur = Village.objects.create(
            name="Othiyathur",
            district=self.district,
            taluk=self.kanda,
            official_code="142",
            official_source="https://example.test/othiyathur.pdf",
        )
        Village.objects.create(
            name="Othiyathur",
            district=self.district,
            taluk=self.gingee,
            official_code="89",
        )
        self.twin_ottampattu = Village.objects.create(
            name="Ottampattu",
            district=self.district,
            taluk=self.kanda,
            official_code="133",
        )
        Village.objects.create(
            name="Ottampattu",
            district=self.district,
            taluk=self.gingee,
            official_code="117",
        )
        Village.objects.create(
            name="Kolathur",
            district=self.district,
            taluk=self.villupuram_taluk,
            official_code="99",
        )
        Village.objects.create(
            name="Kolathur",
            district=self.district,
            taluk=self.marakkanam,
            official_code="203",
        )
        Village.objects.create(
            name="Koralur",
            district=self.district,
            taluk=self.tindi,
            official_code="",
        )
        Village.objects.create(
            name="Koralur",
            district=self.district,
            taluk=self.vikki,
            official_code="040",
        )

        self.legacy_othiyathur = Village.objects.create(
            name="Othiyathur", district=self.district, taluk=None
        )
        self.legacy_ottampattu = Village.objects.create(
            name="Ottampattu", district=self.district, taluk=None
        )
        self.legacy_kolathur = Village.objects.create(
            name="Kolathur", district=self.district, taluk=None
        )
        self.legacy_koralur = Village.objects.create(
            name="Koralur", district=self.district, taluk=None
        )

        self.f_oth = Farmer.objects.create(
            name="Arumugam Othiyathur",
            phone="9000001001",
            district=self.district,
            village=self.legacy_othiyathur,
        )
        self.f_ott = Farmer.objects.create(
            name="Kannan Ottampattu",
            phone="9000001002",
            district=self.district,
            village=self.legacy_ottampattu,
        )
        self.f_kol = Farmer.objects.create(
            name="Chinnaraj Koodalur",
            phone="9000001003",
            district=self.district,
            village=self.legacy_kolathur,
        )
        self.f_kor = Farmer.objects.create(
            name="Rajendran Koralur",
            phone="9000001004",
            district=self.district,
            village=self.legacy_koralur,
        )

    def test_ambiguous_villages_are_not_guessed(self):
        report = apply_safe_manual_matches(dry_run=False)
        accepted = {row["legacy_name"] for row in report["accepted_legacy_unresolved"]}
        self.assertEqual(accepted, {"Kolathur", "Koralur"})
        self.assertEqual(
            {row["classification"] for row in report["accepted_legacy_unresolved"]},
            {"ACCEPTED_LEGACY_UNRESOLVED"},
        )
        self.assertEqual(report["unexpected_unresolved"], [])
        self.legacy_kolathur.refresh_from_db()
        self.legacy_koralur.refresh_from_db()
        self.assertIsNone(self.legacy_kolathur.taluk_id)
        self.assertIsNone(self.legacy_koralur.taluk_id)
        self.assertEqual(self.legacy_kolathur.official_code, "")
        self.assertTrue(self.legacy_kolathur.is_active)
        self.assertTrue(self.legacy_koralur.is_active)
        self.f_kol.refresh_from_db()
        self.f_kor.refresh_from_db()
        self.assertIsNone(self.f_kol.taluk_id)
        self.assertIsNone(self.f_kor.taluk_id)
        self.assertEqual(self.f_kol.village_id, self.legacy_kolathur.id)
        self.assertEqual(self.f_kor.village_id, self.legacy_koralur.id)
        self.assertEqual(self.f_kol.district_id, self.district.id)

    def test_safe_villages_get_taluk_and_farmer_taluk_without_fk_swap(self):
        report = apply_safe_manual_matches(dry_run=False)
        resolved_names = {row["name"] for row in report["resolved"]}
        self.assertEqual(resolved_names, {"Othiyathur", "Ottampattu"})

        self.legacy_othiyathur.refresh_from_db()
        self.legacy_ottampattu.refresh_from_db()
        self.assertEqual(self.legacy_othiyathur.taluk_id, self.kanda.id)
        self.assertEqual(self.legacy_othiyathur.official_code, "142")
        self.assertEqual(self.legacy_ottampattu.taluk_id, self.kanda.id)
        self.assertEqual(self.legacy_ottampattu.official_code, "133")
        self.assertEqual(self.legacy_othiyathur.district_id, self.district.id)

        self.f_oth.refresh_from_db()
        self.f_ott.refresh_from_db()
        self.assertEqual(self.f_oth.village_id, self.legacy_othiyathur.id)
        self.assertEqual(self.f_ott.village_id, self.legacy_ottampattu.id)
        self.assertEqual(self.f_oth.taluk_id, self.kanda.id)
        self.assertEqual(self.f_ott.taluk_id, self.kanda.id)
        self.assertEqual(self.f_oth.district_id, self.district.id)

        # Twin identity released; Farmer FK stays on legacy.
        self.twin_othiyathur.refresh_from_db()
        self.twin_ottampattu.refresh_from_db()
        self.assertEqual(self.twin_othiyathur.official_code, "")
        self.assertFalse(self.twin_othiyathur.is_active)
        self.assertEqual(self.twin_ottampattu.official_code, "")
        self.assertFalse(self.twin_ottampattu.is_active)
        self.assertEqual(
            self.legacy_othiyathur.official_source,
            "https://example.test/othiyathur.pdf",
        )

    def test_command_is_idempotent(self):
        call_command("resolve_backfill_review")
        call_command("resolve_backfill_review")
        self.legacy_othiyathur.refresh_from_db()
        self.assertEqual(self.legacy_othiyathur.taluk_id, self.kanda.id)
        self.assertEqual(self.legacy_othiyathur.official_code, "142")
        self.assertEqual(
            Village.objects.filter(name__iexact="Othiyathur", taluk__isnull=True).count(),
            0,
        )
        self.assertEqual(
            Village.objects.filter(
                name__iexact="Othiyathur",
                taluk=self.kanda,
                official_code="142",
            ).count(),
            1,
        )
        # Accepted remain unlinked
        self.assertTrue(
            Village.objects.filter(name__iexact="Kolathur", taluk__isnull=True).exists()
        )
        self.assertEqual(len(ACCEPTED_LEGACY_UNRESOLVED), 2)
        report = apply_safe_manual_matches(dry_run=False)
        self.assertEqual(report["resolved"], [])
        self.assertEqual(len(report["skipped_already_linked"]), 2)
        self.assertEqual(report["unexpected_unresolved"], [])
