"""Phase 3B: --apply mode tests for canonical_crop_pest_disease.

Covers safety gates, transactional import, is_canonical master selection,
legacy duplicate inactivation, Visit protection and idempotency.  Fixtures
use distinctive Zz-prefixed names so migration-seeded data never collides.
Django's test runner uses a throwaway test database.
"""
import json
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from masters.canonical_dataset import (
    ApplyGateError,
    apply_gates,
    apply_import,
    build_dry_run_plan,
    plan_summary,
)
from masters.models import (
    Crop,
    CropProblem,
    ProblemCategory,
    ProblemMaster,
)
from visits.models import Visit

DISEASE = "disease"
PEST = "pest"


def _mini(crop_en="ZzCanonCrop", crop_ta="அ",
          pests=None, diseases=None):
    return [{
        "seq": 1,
        "page": 1,
        "crop": {"name_en": crop_en, "name_ta": crop_ta},
        "pests": pests or [],
        "diseases": diseases or [],
    }]


def _cats(disease_active=True):
    pest, _ = ProblemCategory.objects.get_or_create(
        code=PEST, defaults={"name": "Pest", "requires_problem_master": True,
                             "is_active": True})
    disease, _ = ProblemCategory.objects.get_or_create(
        code=DISEASE, defaults={"name": "Disease",
                                "requires_problem_master": True,
                                "is_active": disease_active})
    return pest, disease


def _crop(en, ta="", active=True):
    return Crop.objects.create(name_en=en, name_ta=ta, is_active=active)


def _master(cat, name, ta="", crop=None, active=True, canonical=False):
    return ProblemMaster.objects.create(
        category=cat, name=name, tamil_name=ta, crop=crop,
        is_active=active, is_canonical=canonical)


def _counts():
    return {
        "crop": Crop.objects.count(),
        "master": ProblemMaster.objects.count(),
        "mapping": CropProblem.objects.count(),
        "visit": Visit.objects.count(),
    }


def _tmp_file(name, payload):
    d = Path(settings.BASE_DIR) / ".test_tmp_cpd"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(payload, encoding="utf-8")
    return p


class ApplyGateTests(TestCase):
    """Safety gates: --apply must refuse unless every gate passes."""

    def setUp(self):
        self.pest_cat, self.dis_cat = _cats()

    def test_01_apply_requires_explicit_flag(self):
        out = StringIO()
        err = StringIO()
        before = _counts()
        call_command("canonical_crop_pest_disease",
                     stdout=out, stderr=err)
        self.assertIn("Specify --validate", err.getvalue())
        self.assertEqual(before, _counts())

    def test_02_dry_run_writes_zero_rows(self):
        data = _mini(pests=[{"name_en": "ZzP1", "name_ta": "அ"}])
        f = _tmp_file("canon_02.json", json.dumps(data))
        before = _counts()
        call_command("canonical_crop_pest_disease", "--dry-run",
                     "--canonical-file", str(f),
                     stdout=StringIO())
        self.assertEqual(before, _counts())

    def test_03_production_audit_writes_zero_rows(self):
        data = _mini(pests=[{"name_en": "ZzP2", "name_ta": "அ"}])
        f = _tmp_file("canon_03.json", json.dumps(data))
        before = _counts()
        call_command("canonical_crop_pest_disease", "--production-audit",
                     "--canonical-file", str(f),
                     stdout=StringIO())
        self.assertEqual(before, _counts())

    def test_04_master_duplicates_do_not_block_apply(self):
        # legacy duplicate masters are historical display data -- not a gate
        a = _master(self.pest_cat, "ZzAmbPest")
        b = _master(self.pest_cat, "ZzAmbPest")
        data = _mini(pests=[{"name_en": "ZzAmbPest", "name_ta": "அ"}])
        self.assertEqual(apply_gates(data), [])
        stats = apply_import(data)
        self.assertEqual(stats["masters_created"], 1)
        canon = ProblemMaster.objects.get(name="ZzAmbPest", is_canonical=True)
        self.assertNotIn(canon.id, (a.id, b.id))

    def test_05_ambiguous_canonical_crop_blocks_apply(self):
        _crop("ZzDupCrop", "", active=True)
        _crop("ZzDupCrop", "", active=True)
        data = _mini(crop_en="ZzDupCrop",
                     pests=[{"name_en": "ZzP5", "name_ta": "அ"}])
        errors = apply_gates(data)
        self.assertTrue(any("ambiguous canonical crop" in e for e in errors))
        with self.assertRaises(ApplyGateError):
            apply_import(data)

    def test_06_missing_category_blocks_apply(self):
        self.dis_cat.delete()
        data = _mini(diseases=[{"name_en": "ZzD6", "name_ta": "ஆ"}])
        errors = apply_gates(data)
        self.assertTrue(any("category" in e for e in errors))
        with self.assertRaises(ApplyGateError):
            apply_import(data)


class ApplyBehaviourTests(TestCase):
    """Real apply behaviour on a throwaway test DB."""

    def setUp(self):
        self.pest_cat, self.dis_cat = _cats()
        self.crop = _crop("ZzCanonCrop", "அ")

    def test_08_ambiguous_group_creates_fresh_canonical_master(self):
        a = _master(self.pest_cat, "ZzAmbPest8")
        b = _master(self.pest_cat, "ZzAmbPest8")
        data = _mini(pests=[{"name_en": "ZzAmbPest8", "name_ta": "அ"}])
        apply_import(data)
        canon = ProblemMaster.objects.get(name="ZzAmbPest8",
                                          is_canonical=True)
        self.assertNotIn(canon.id, (a.id, b.id))
        self.assertTrue(canon.is_active)
        cp = CropProblem.objects.get(crop=self.crop)
        self.assertEqual(cp.problem_master_id, canon.id)

    def test_09_legacy_duplicates_inactivated_not_deleted(self):
        a = _master(self.pest_cat, "ZzAmbPest9")
        b = _master(self.pest_cat, "ZzAmbPest9")
        data = _mini(pests=[{"name_en": "ZzAmbPest9", "name_ta": "அ"}])
        apply_import(data)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertFalse(b.is_active)
        self.assertFalse(a.is_canonical)
        self.assertFalse(b.is_canonical)

    def test_10_historical_visit_fk_unchanged(self):
        a = _master(self.pest_cat, "ZzAmbPest10")
        _master(self.pest_cat, "ZzAmbPest10")
        u = get_user_model().objects.create_user(username="t10", password="x")
        v = Visit.objects.create(employee=u, crop=self.crop, problem_master=a)
        data = _mini(pests=[{"name_en": "ZzAmbPest10", "name_ta": "அ"}])
        apply_import(data)
        v.refresh_from_db()
        self.assertEqual(v.problem_master_id, a.id)  # still points at legacy

    def test_11_historical_visit_m2m_unchanged(self):
        a = _master(self.pest_cat, "ZzAmbPest11")
        _master(self.pest_cat, "ZzAmbPest11")
        u = get_user_model().objects.create_user(username="t11", password="x")
        v = Visit.objects.create(employee=u, crop=self.crop, problem_master=a)
        v.problem_items.set([a])
        data = _mini(pests=[{"name_en": "ZzAmbPest11", "name_ta": "அ"}])
        apply_import(data)
        self.assertEqual(
            list(v.problem_items.values_list("id", flat=True)), [a.id])

    def test_12_near_variant_not_reused(self):
        variant = _master(self.pest_cat, "ZzCaseBug")
        data = _mini(pests=[{"name_en": "ZzCasebug", "name_ta": "அ"}])
        stats = apply_import(data)
        self.assertEqual(stats["masters_created"], 1)
        new = ProblemMaster.objects.get(name="ZzCasebug")
        self.assertNotEqual(new.id, variant.id)
        self.assertTrue(new.is_canonical)
        cp = CropProblem.objects.get(crop=self.crop)
        self.assertEqual(cp.problem_master_id, new.id)
        variant.refresh_from_db()
        self.assertFalse(variant.is_active)

    def test_13_missing_exact_name_creates_new_master(self):
        data = _mini(diseases=[{"name_en": "ZzNewDisease", "name_ta": "ஆ"}])
        stats = apply_import(data)
        self.assertEqual(stats["masters_created"], 1)
        m = ProblemMaster.objects.get(category=self.dis_cat,
                                      name="ZzNewDisease")
        self.assertTrue(m.is_active)
        self.assertTrue(m.is_canonical)
        self.assertEqual(m.tamil_name, "ஆ")

    def test_13b_single_unambiguous_legacy_row_adopted(self):
        m = _master(self.pest_cat, "ZzSinglePest")
        data = _mini(pests=[{"name_en": "ZzSinglePest", "name_ta": "அ"}])
        stats = apply_import(data)
        self.assertEqual(stats["masters_created"], 0)
        self.assertEqual(stats["masters_adopted"], 1)
        m.refresh_from_db()
        self.assertTrue(m.is_canonical)
        self.assertTrue(m.is_active)
        cp = CropProblem.objects.get(crop=self.crop)
        self.assertEqual(cp.problem_master_id, m.id)

    def test_14_shared_master_stays_active(self):
        legacy = _crop("ZzLegacyCrop14", "")
        shared = _master(self.pest_cat, "ZzSharedPest14")
        CropProblem.objects.create(crop=self.crop, problem_master=shared)
        CropProblem.objects.create(crop=legacy, problem_master=shared)
        data = _mini(pests=[{"name_en": "ZzSharedPest14", "name_ta": "அ"}])
        apply_import(data)
        shared.refresh_from_db()
        self.assertTrue(shared.is_active)
        self.assertTrue(shared.is_canonical)
        self.assertTrue(CropProblem.objects.filter(
            crop=self.crop, problem_master=shared).exists())
        self.assertFalse(CropProblem.objects.filter(
            crop=legacy, problem_master=shared).exists())

    def test_15_noncanonical_unused_master_becomes_inactive(self):
        m = _master(self.pest_cat, "ZzOrphanPest15")
        data = _mini(pests=[{"name_en": "ZzOtherPest15", "name_ta": "அ"}])
        apply_import(data)
        m.refresh_from_db()
        self.assertFalse(m.is_active)
        self.assertTrue(ProblemMaster.objects.filter(pk=m.pk).exists())

    def test_16_noncanonical_mapping_removed(self):
        m = _master(self.pest_cat, "ZzOrphanPest16")
        cp = CropProblem.objects.create(crop=self.crop, problem_master=m)
        data = _mini(pests=[{"name_en": "ZzOtherPest16", "name_ta": "அ"}])
        stats = apply_import(data)
        self.assertFalse(CropProblem.objects.filter(pk=cp.pk).exists())
        self.assertGreaterEqual(stats["mappings_removed"], 1)

    def test_17_canonical_mapping_created(self):
        m = _master(self.pest_cat, "ZzMapPest17")
        data = _mini(pests=[{"name_en": "ZzMapPest17", "name_ta": "அ"}])
        stats = apply_import(data)
        self.assertTrue(CropProblem.objects.filter(
            crop=self.crop, problem_master=m).exists())
        self.assertEqual(stats["mappings_created"], 1)

    def test_18_groundnut_duplicate_creates_one_mapping(self):
        m = _master(self.dis_cat, "ZzDupRot")
        data = _mini(diseases=[
            {"name_en": "ZzDupRot", "name_ta": "ஆ"},
            {"name_en": "ZzDupRot", "name_ta": "ஆ"},  # in-crop source duplicate
        ])
        stats = apply_import(data)
        self.assertEqual(
            CropProblem.objects.filter(
                crop=self.crop, problem_master=m).count(), 1)
        self.assertEqual(stats["mappings_created"], 1)

    def test_19_disease_category_reused_and_activated(self):
        self.dis_cat.is_active = False
        self.dis_cat.save(update_fields=["is_active"])
        data = _mini(diseases=[{"name_en": "ZzD19", "name_ta": "ஆ"}])
        stats = apply_import(data)
        self.dis_cat.refresh_from_db()
        self.assertTrue(self.dis_cat.is_active)
        self.assertEqual(stats["categories_activated"], 1)

    def test_20_no_duplicate_disease_category(self):
        before = ProblemCategory.objects.filter(code=DISEASE).count()
        data = _mini(diseases=[{"name_en": "ZzD20", "name_ta": "ஆ"}])
        apply_import(data)
        self.assertEqual(
            ProblemCategory.objects.filter(code=DISEASE).count(), before)

    def test_21_transaction_rolls_back_on_injected_failure(self):
        _master(self.pest_cat, "ZzRollbackPest")
        legacy = _crop("ZzLegacyCrop21", "", active=True)
        data = _mini(
            crop_en="ZzCanonCrop",
            pests=[{"name_en": "ZzRollbackPest", "name_ta": "அ"}],
            diseases=[{"name_en": "ZzRollbackDisease", "name_ta": "ஆ"}])
        before = _counts()
        before_crop_active = Crop.objects.get(pk=legacy.pk).is_active
        with mock.patch.object(
                CropProblem.objects, "create",
                side_effect=RuntimeError("injected mid-apply failure")):
            with self.assertRaises(RuntimeError):
                apply_import(data)
        after = _counts()
        # master created + crop updates + category activation all rolled back
        self.assertEqual(before["mapping"], after["mapping"])
        self.assertEqual(
            Crop.objects.get(pk=legacy.pk).is_active, before_crop_active)
        self.assertFalse(ProblemMaster.objects.filter(
            name="ZzRollbackDisease").exists())

    def test_22_repeated_apply_is_idempotent(self):
        # duplicate legacy rows on first run -> fresh canonical created once;
        # second run reuses the is_canonical row instead of creating another.
        _master(self.pest_cat, "ZzAmbPest22")
        _master(self.pest_cat, "ZzAmbPest22")
        data = _mini(
            pests=[{"name_en": "ZzAmbPest22", "name_ta": "அ"},
                   {"name_en": "ZzIdemPest", "name_ta": "அ"}],
            diseases=[{"name_en": "ZzIdemDisease", "name_ta": "ஆ"}])
        stats1 = apply_import(data)
        self.assertEqual(stats1["masters_created"], 3)
        stats2 = apply_import(data)
        self.assertEqual(stats2["masters_created"], 0)
        self.assertEqual(stats2["mappings_created"], 0)
        self.assertEqual(stats2["mappings_removed"], 0)
        self.assertEqual(stats2["crops_created"], 0)
        self.assertEqual(
            ProblemMaster.objects.filter(
                name="ZzAmbPest22", is_canonical=True).count(), 1)

    def test_23_post_apply_dry_run_converges(self):
        _master(self.pest_cat, "ZzAmbPest23")
        _master(self.pest_cat, "ZzAmbPest23")
        data = _mini(
            pests=[{"name_en": "ZzAmbPest23", "name_ta": "அ"},
                   {"name_en": "ZzConvPest", "name_ta": "அ"}],
            diseases=[{"name_en": "ZzConvDisease", "name_ta": "ஆ"}])
        apply_import(data)
        plan = build_dry_run_plan(data)
        s = plan_summary(plan)
        self.assertEqual(s["ambiguous"], 0)
        self.assertEqual(s["pests_create"], 0)
        self.assertEqual(s["diseases_create"], 0)
        self.assertEqual(s["mappings_create"], 0)
        self.assertEqual(s["mappings_remove"], 0)
        self.assertEqual(s["crops_create"], 0)
        self.assertEqual(s["crops_update"], 0)


class ApplyCommandGatesTests(TestCase):
    """Command-level checks: --apply refuses via SystemExit on gate failure."""

    def setUp(self):
        self.pest_cat, self.dis_cat = _cats()

    def test_command_apply_executes_with_duplicates(self):
        _master(self.pest_cat, "ZzCmdAmb")
        _master(self.pest_cat, "ZzCmdAmb")
        data = _mini(pests=[{"name_en": "ZzCmdAmb", "name_ta": "அ"}])
        f = _tmp_file("canon_cmd.json", json.dumps(data))
        out = StringIO()
        call_command("canonical_crop_pest_disease", "--apply",
                     "--canonical-file", str(f), stdout=out)
        self.assertIn("APPLY COMPLETE", out.getvalue())
        canon = ProblemMaster.objects.get(name="ZzCmdAmb", is_canonical=True)
        cp = CropProblem.objects.get(crop__name_en="ZzCanonCrop")
        self.assertEqual(cp.problem_master_id, canon.id)
        self.assertEqual(
            ProblemMaster.objects.filter(
                name="ZzCmdAmb", is_active=True).count(), 1)

    def test_command_apply_refuses_on_ambiguous_crop(self):
        _crop("ZzDupCropCmd", "", active=True)
        _crop("ZzDupCropCmd", "", active=True)
        data = _mini(crop_en="ZzDupCropCmd",
                     pests=[{"name_en": "ZzP", "name_ta": "அ"}])
        f = _tmp_file("canon_cmd2.json", json.dumps(data))
        before = _counts()
        with self.assertRaises(SystemExit):
            call_command("canonical_crop_pest_disease", "--apply",
                         "--canonical-file", str(f),
                         stdout=StringIO(), stderr=StringIO())
        self.assertEqual(before, _counts())
