"""Tests for the Phase-2A canonical Crop -> Pest/Disease dataset.

Covers canonical-JSON validation AND the read-only dry-run planner.  The
dry-run tests build small synthetic canonical fixtures so the plan can be
asserted deterministically against controlled DB rows.  The test DB is seeded
by data migrations, so fixtures use distinctive names and ``get_or_create``
where a single exact match is required.  Nothing here writes to a real
database -- Django's test runner uses a throwaway test DB.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from masters.canonical_dataset import (
    CANONICAL_PATH,
    TAMIL_REVIEW_REQUIRED,
    analyze_variants,
    build_dry_run_plan,
    is_valid_tamil_value,
    load_canonical,
    plan_summary,
    validate_canonical,
    DISEASE,
    PEST,
)
from masters.models import (
    Crop,
    CropProblem,
    ProblemCategory,
    ProblemMaster,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _mini_canonical(crop_en="Amla", crop_ta="நெல்லிக்காய்",
                    pests=None, diseases=None):
    """Build a tiny canonical list in the same shape as the real JSON."""
    return [{
        "seq": 1,
        "page": 1,
        "crop": {"name_en": crop_en, "name_ta": crop_ta},
        "pests": pests or [],
        "diseases": diseases or [],
    }]


def _cats():
    pest, _ = ProblemCategory.objects.get_or_create(
        code=PEST, defaults={"name": "Pest",
                             "requires_problem_master": True,
                             "is_active": True})
    disease, _ = ProblemCategory.objects.get_or_create(
        code=DISEASE, defaults={"name": "Disease",
                                "requires_problem_master": True,
                                "is_active": True})
    return pest, disease


def _crop(en, ta="", active=True):
    c, created = Crop.objects.get_or_create(
        name_en=en, defaults={"name_ta": ta, "is_active": active})
    if not created:
        c.name_ta = ta
        c.is_active = active
        c.save()
    return c


def _master(cat, name, ta="", crop=None, active=True):
    return ProblemMaster.objects.create(
        category=cat, name=name, tamil_name=ta, crop=crop, is_active=active)


# ----------------------------------------------------------------------
# 1-7: canonical JSON validation
# ----------------------------------------------------------------------

class CanonicalJsonValidationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.data = load_canonical()

    def test_01_canonical_json_loads(self):
        self.assertIsInstance(self.data, list)
        self.assertGreater(len(self.data), 0)

    def test_02_every_crop_has_pests_and_diseases(self):
        for e in self.data:
            self.assertIn("pests", e)
            self.assertIn("diseases", e)
            self.assertIsInstance(e["pests"], list)
            self.assertIsInstance(e["diseases"], list)

    def test_03_valid_field_shape(self):
        for e in self.data:
            self.assertIn("name_en", e["crop"])
            self.assertIn("name_ta", e["crop"])
            for kind in ("pests", "diseases"):
                for it in e[kind]:
                    self.assertEqual(set(it.keys()), {"name_en", "name_ta"})

    def test_04_no_corrupted_tamil(self):
        rep = validate_canonical(self.data)
        self.assertEqual(rep.errors, [])
        for e in self.data:
            self.assertTrue(is_valid_tamil_value(e["crop"]["name_ta"]))
            for kind in ("pests", "diseases"):
                for it in e[kind]:
                    self.assertTrue(is_valid_tamil_value(it["name_ta"]),
                                    f"{it['name_en']} -> {it['name_ta']!r}")

    def test_04b_corrupted_tamil_detected(self):
        bad = _mini_canonical(pests=[{"name_en": "Aphid",
                                      "name_ta": "(cid:131)xyz"}])
        rep = validate_canonical(bad)
        self.assertTrue(any("corrupted" in e for e in rep.errors))
        self.assertFalse(is_valid_tamil_value("(cid:131)xyz"))
        self.assertFalse(is_valid_tamil_value("garbled\ufffdtext"))
        self.assertFalse(is_valid_tamil_value("english only"))

    def test_05_tamil_review_required_reported(self):
        data = _mini_canonical(
            pests=[{"name_en": "Aphid", "name_ta": TAMIL_REVIEW_REQUIRED}])
        rep = validate_canonical(data)
        self.assertTrue(rep.tamil_review_required)
        self.assertFalse(rep.errors)  # sentinel is valid, just reported

    def test_06_exact_duplicate_within_crop_reported(self):
        data = _mini_canonical(pests=[
            {"name_en": "Aphid", "name_ta": "x"},
            {"name_en": "Aphid", "name_ta": "y"},
        ])
        rep = validate_canonical(data)
        self.assertTrue(rep.duplicates_within_crop)

    def test_06b_real_duplicate_groundnut_stem_rot(self):
        # The source PDF lists "Stem rot" twice under Groundnut -- confirm it
        # is surfaced as an in-crop duplicate rather than silently dropped.
        rep = validate_canonical(self.data)
        self.assertTrue(any("Stem rot" in d for d in rep.duplicates_within_crop))

    def test_07_pest_disease_independent(self):
        # Same English name under different categories stays distinct.
        data = _mini_canonical(
            pests=[{"name_en": "Spot", "name_ta": "அ"}],
            diseases=[{"name_en": "Spot", "name_ta": "ஆ"}])
        rep = validate_canonical(data)
        self.assertFalse(rep.errors)
        self.assertEqual(len(data[0]["pests"]), 1)
        self.assertEqual(len(data[0]["diseases"]), 1)

    def test_07b_cross_column_detected(self):
        # a clearly-disease word inside pests is surfaced for review...
        data = _mini_canonical(pests=[{"name_en": "Powdery Mildew",
                                       "name_ta": "அ"}])
        rep = validate_canonical(data)
        self.assertTrue(rep.suspect_cross_column)
        # ...and a clearly-pest word inside diseases is flagged too
        data2 = _mini_canonical(diseases=[{"name_en": "Aphid",
                                           "name_ta": "அ"}])
        rep2 = validate_canonical(data2)
        self.assertTrue(rep2.suspect_cross_column)


# ----------------------------------------------------------------------
# 8-16: read-only dry-run planner
# ----------------------------------------------------------------------

class DryRunPlannerTests(TestCase):

    def setUp(self):
        self.pest_cat, self.dis_cat = _cats()

    def _counts(self):
        return {
            "crop": Crop.objects.count(),
            "master": ProblemMaster.objects.count(),
            "mapping": CropProblem.objects.count(),
        }

    def test_08_dry_run_writes_zero_rows(self):
        _crop("ZzDryRunCropA", "நெல்லிக்காய்")
        data = _mini_canonical(crop_en="ZzDryRunCropA",
                               pests=[{"name_en": "ZzTestPest", "name_ta": "அ"}])
        before = self._counts()
        build_dry_run_plan(data)
        self.assertEqual(before, self._counts())

    def test_09_exact_existing_crop_reusable(self):
        _crop("ZzDryRunCropB", "நெல்லிக்காய்")
        plan = build_dry_run_plan(
            _mini_canonical(crop_en="ZzDryRunCropB", crop_ta="நெல்லிக்காய்"))
        keeps = [k["crop"] for k in plan["crops"]["keep"]]
        self.assertIn("ZzDryRunCropB", keeps)
        self.assertNotIn("ZzDryRunCropB",
                         [c["crop"] for c in plan["crops"]["create"]])

    def test_10_missing_crop_planned_create(self):
        plan = build_dry_run_plan(
            _mini_canonical(crop_en="ZzNoSuchCrop", crop_ta="வாழை"))
        creates = [c["crop"] for c in plan["crops"]["create"]]
        self.assertIn("ZzNoSuchCrop", creates)

    def test_11_legacy_crop_planned_inactive(self):
        _crop("ZzLegacyOnlyCrop", "", active=True)
        plan = build_dry_run_plan(
            _mini_canonical(crop_en="ZzDryRunCropC", crop_ta="x"))
        dec = [d["crop"] for d in plan["crops"]["deactivate"]]
        self.assertIn("ZzLegacyOnlyCrop", dec)

    def test_12_reusable_master_detected(self):
        _crop("ZzDryRunCropD", "நெல்லிக்காய்")
        _master(self.pest_cat, "ZzTestAphid")
        data = _mini_canonical(
            crop_en="ZzDryRunCropD",
            pests=[{"name_en": "ZzTestAphid", "name_ta": "அ"}])
        plan = build_dry_run_plan(data)
        reuse = [r["master"] for r in plan["pests"]["reuse"]]
        self.assertIn("ZzTestAphid", reuse)
        self.assertNotIn("zztestaphid",
                         [c["master"] for c in plan["pests"]["create"]])

    def test_13_shared_master_remains_active(self):
        """A master mapped to a canonical crop stays active even though a
        non-canonical crop also references it -- only the non-canonical
        crop's mapping is removed; the master is NOT deactivated."""
        can = _crop("ZzDryRunCropE", "நெல்லிக்காய்")
        legacy = _crop("ZzLegacyCropE", "", active=True)
        shared = _master(self.pest_cat, "ZzSharedBug")
        CropProblem.objects.create(crop=can, problem_master=shared)
        CropProblem.objects.create(crop=legacy, problem_master=shared)
        data = _mini_canonical(
            crop_en="ZzDryRunCropE",
            pests=[{"name_en": "ZzSharedBug", "name_ta": "அ"}])
        plan = build_dry_run_plan(data)
        # shared master reused/kept, never deactivated
        self.assertFalse(any(d["master"] == "ZzSharedBug"
                             for d in plan["pests"]["deactivate"]))
        # only the legacy crop's mapping removed
        removed = plan["mappings"]["remove"]
        self.assertTrue(any(r["crop"] == "zzlegacycrope"
                            and r["master"] == "zzsharedbug"
                            for r in removed))
        # canonical mapping kept
        self.assertTrue(any(k["crop"] == "zzdryruncrope"
                            and k["master"] == "zzsharedbug"
                            for k in plan["mappings"]["keep"]))

    def test_14_noncanonical_mapping_removal_only(self):
        can = _crop("ZzDryRunCropF", "நெல்லிக்காய்")
        m = _master(self.pest_cat, "ZzOrphanPest")
        CropProblem.objects.create(crop=can, problem_master=m)
        # canonical data does NOT map ZzOrphanPest to this crop -> removal
        data = _mini_canonical(
            crop_en="ZzDryRunCropF",
            pests=[{"name_en": "ZzOtherPest", "name_ta": "அ"}])
        plan = build_dry_run_plan(data)
        removed = plan["mappings"]["remove"]
        self.assertTrue(any(r["master"] == "zzorphanpest" for r in removed))
        # non-canonical master planned for deactivation (not deletion)
        self.assertTrue(any(d["master"] == "ZzOrphanPest"
                            for d in plan["pests"]["deactivate"]))
        self.assertTrue(ProblemMaster.objects.filter(pk=m.pk).exists())

    def test_15_historical_referenced_legacy_preserved(self):
        User = get_user_model()
        user = User.objects.create_user(username="t_canon", password="x")
        legacy_master = _master(self.pest_cat, "ZzOldWorm")
        legacy_crop = _crop("ZzLegacyCropG", "", active=True)
        from visits.models import Visit
        v = Visit.objects.create(employee=user, crop=legacy_crop,
                                 problem_master=legacy_master)
        data = _mini_canonical(crop_en="ZzDryRunCropG", crop_ta="x")
        plan = build_dry_run_plan(data)
        hist = plan["history"]["referenced_legacy"]
        names = {h["name"] for h in hist}
        self.assertIn("ZzOldWorm", names)
        self.assertIn("ZzLegacyCropG", names)
        # deactivation is planned (soft), the record itself is preserved
        self.assertTrue(any(d["master"] == "ZzOldWorm"
                            for d in plan["pests"]["deactivate"]))
        self.assertTrue(ProblemMaster.objects.filter(pk=legacy_master.pk).exists())
        self.assertTrue(Visit.objects.filter(pk=v.pk).exists())

    def test_16_second_dry_run_same_plan(self):
        _crop("ZzDryRunCropH", "நெல்லிக்காய்")
        _master(self.pest_cat, "ZzIdemPest")
        data = _mini_canonical(
            crop_en="ZzDryRunCropH",
            pests=[{"name_en": "ZzIdemPest", "name_ta": "அ"}])
        p1 = build_dry_run_plan(data)
        p2 = build_dry_run_plan(data)
        self.assertEqual(plan_summary(p1), plan_summary(p2))
        self.assertEqual(json.dumps(p1, sort_keys=True, default=str),
                         json.dumps(p2, sort_keys=True, default=str))


# ----------------------------------------------------------------------
# Real-file end-to-end sanity (real canonical JSON in test DB)
# ----------------------------------------------------------------------

class RealCanonicalDryRunTests(TestCase):
    """Run the real 54-crop canonical file through validation + dry-run.
    Confirms the file is well-formed end-to-end and that planning performs
    zero writes.  The test DB is seeded by migrations, so assertions are
    structural (partition counts) rather than absolute."""

    @classmethod
    def setUpTestData(cls):
        cls.data = load_canonical()

    def test_real_file_validates(self):
        rep = validate_canonical(self.data)
        self.assertEqual(rep.errors, [])

    def test_real_file_structure(self):
        # 54 crops; pests/diseases kept as independent collections
        self.assertEqual(len(self.data), 54)
        self.assertTrue(all(isinstance(e["pests"], list) for e in self.data))
        self.assertTrue(all(isinstance(e["diseases"], list) for e in self.data))

    def test_real_file_dry_run_zero_writes(self):
        before = {
            "crop": Crop.objects.count(),
            "master": ProblemMaster.objects.count(),
            "mapping": CropProblem.objects.count(),
        }
        plan = build_dry_run_plan(self.data)
        after = {
            "crop": Crop.objects.count(),
            "master": ProblemMaster.objects.count(),
            "mapping": CropProblem.objects.count(),
        }
        self.assertEqual(before, after)
        s = plan_summary(plan)
        # every canonical crop resolves to exactly one of create/update/keep
        self.assertEqual(
            s["crops_create"] + s["crops_update"] + s["crops_keep"], 54)
        # every canonical (crop,category,master) association resolves to
        # exactly one of create/keep
        expected = set()
        for e in self.data:
            cn = e["crop"]["name_en"].strip().lower()
            for kind, code in (("pests", "pest"), ("diseases", "disease")):
                for it in e[kind]:
                    expected.add((cn, code, it["name_en"].strip().lower()))
        self.assertEqual(s["mappings_create"] + s["mappings_keep"],
                         len(expected))
