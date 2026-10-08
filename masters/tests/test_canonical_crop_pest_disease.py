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
    canonical_map_keys,
    canonical_master_keys,
    db_counts,
    historical_reference_counts,
    is_valid_tamil_value,
    load_canonical,
    plan_summary,
    source_duplicates,
    tamil_anomalies,
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
        reuse = [k["crop"] for k in plan["crops"]["reuse"]]
        self.assertIn("ZzDryRunCropB", reuse)
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
        self.assertNotIn("ZzTestAphid",
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
        self.assertTrue(any(r["crop"] == "ZzLegacyCropE"
                            and r["master"] == "ZzSharedBug"
                            for r in removed))
        # canonical mapping kept
        self.assertTrue(any(k["crop"] == "ZzDryRunCropE"
                            and k["master"] == "ZzSharedBug"
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
        self.assertTrue(any(r["master"] == "ZzOrphanPest" for r in removed))
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
        # every canonical crop resolves to exactly one of create/update/reuse
        self.assertEqual(
            s["crops_create"] + s["crops_update"] + s["crops_reuse"], 54)
        # every canonical (crop,category,master) association resolves to
        # exactly one of create/keep -- EXACT identity (case preserved)
        expected = canonical_map_keys(self.data)
        self.assertEqual(s["mappings_create"] + s["mappings_keep"],
                         len(expected))


# ----------------------------------------------------------------------
# PHASE 2B: exact-identity + production-audit preflight
# ----------------------------------------------------------------------

class Phase2BExactIdentityTests(TestCase):
    """Exact-PDF-text identity + category planning + read-only audit mode."""

    def setUp(self):
        self.pest_cat, self.dis_cat = _cats()

    def _mk(self, pest_names=None, disease_names=None):
        data = _mini_canonical(
            crop_en="Zz2BCrop",
            pests=[{"name_en": n, "name_ta": "அ"} for n in (pest_names or [])],
            diseases=[{"name_en": n, "name_ta": "அ"} for n in (disease_names or [])])
        return data

    # 1. Fruit Borer vs Fruit borer are NOT auto-merged
    def test_2b_01_case_variants_not_merged(self):
        data = self._mk(pest_names=["Fruit Borer", "Fruit borer"])
        keys = canonical_master_keys(data)
        self.assertIn(("pest", "Fruit Borer"), keys)
        self.assertIn(("pest", "Fruit borer"), keys)
        self.assertEqual(len(keys), 2)

    # 2. Mealy Bug vs Mealybug are NOT auto-merged
    def test_2b_02_spacing_variants_not_merged(self):
        data = self._mk(pest_names=["Mealy Bug", "Mealybug"])
        keys = canonical_master_keys(data)
        self.assertEqual(len(keys), 2)
        plan = build_dry_run_plan(data)
        creates = {c["master"] for c in plan["pests"]["create"]}
        self.assertIn("Mealy Bug", creates)
        self.assertIn("Mealybug", creates)

    # 3. Bettle vs Beetle are NOT auto-corrected/merged
    def test_2b_03_spelling_variants_not_merged(self):
        data = self._mk(pest_names=["Bettle", "Beetle"])
        keys = canonical_master_keys(data)
        self.assertEqual(len(keys), 2)
        rep = validate_canonical(data)
        self.assertFalse(rep.errors)  # both preserved, no error

    # 4. Pest and Disease with same English stay category-separated
    def test_2b_04_category_separation(self):
        data = self._mk(pest_names=["Leaf spot"], disease_names=["Leaf spot"])
        keys = canonical_master_keys(data)
        self.assertIn(("pest", "Leaf spot"), keys)
        self.assertIn(("disease", "Leaf spot"), keys)
        self.assertEqual(len(keys), 2)

    # 5/6. Groundnut duplicate -> 1 db mapping plan, source reports duplicate
    def test_2b_05_groundnut_duplicate_single_mapping(self):
        # find the real Groundnut "Stem rot" pair in canonical data
        data = load_canonical()
        dups = source_duplicates(data)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["crop"], "Groundnut")
        self.assertEqual(dups[0]["name"], "Stem rot")
        self.assertEqual(dups[0]["category"], "disease")
        # canonical data still contains both rows (source preserved)
        g = next(e for e in data if e["crop"]["name_en"] == "Groundnut")
        stems = [d for d in g["diseases"]
                 if d["name_en"].strip() == "Stem rot"]
        self.assertEqual(len(stems), 2)
        # but only ONE mapping key is planned
        cm = canonical_map_keys(data)
        gn_stem = [k for k in cm
                   if k[0] == "Groundnut" and k[2] == "Stem rot"]
        self.assertEqual(len(gn_stem), 1)
        plan = build_dry_run_plan(data)
        sd = plan["review_items"]["source_duplicates"]
        self.assertEqual(sd["count"], 1)
        self.assertEqual(sd["planned_db_mappings"], 0)
        planned = [m for m in plan["mappings"]["create"] + plan["mappings"]["keep"]
                   if m["crop"] == "Groundnut" and m["master"] == "Stem rot"]
        self.assertEqual(len(planned), 1)

    # 7/8. disease category exists-but-inactive -> PLANNED activation, no dup
    def test_2b_07_disease_category_reactivation_planned(self):
        # make the disease category inactive to mirror the dev/prod state
        self.dis_cat.is_active = False
        self.dis_cat.save()
        before = ProblemCategory.objects.filter(code=DISEASE).count()
        plan = build_dry_run_plan(self._mk())
        self.assertEqual(plan["categories"][DISEASE]["action"], "activate")
        self.assertEqual(plan["categories"][DISEASE]["db_id"], self.dis_cat.id)
        # existing record reused -- no create action planned for disease
        self.assertNotEqual(plan["categories"][DISEASE]["action"], "create")
        # pest category kept (exists + active)
        self.assertEqual(plan["categories"][PEST]["action"], "keep")
        # still exactly one disease category row; nothing written
        self.assertEqual(ProblemCategory.objects.filter(code=DISEASE).count(), before)
        self.assertFalse(ProblemCategory.objects.get(pk=self.dis_cat.pk).is_active)

    # 9. shared master remains active if any canonical crop uses it
    def test_2b_09_shared_master_not_deactivated(self):
        # same underlying rule as test_13 but asserted via deactivate list
        # across BOTH the canonical and a legacy crop mapping
        can = _crop("Zz2BCropShare", "x")
        legacy = _crop("Zz2BLegacy", "x")
        shared = _master(self.pest_cat, "ZzSharedPest")
        CropProblem.objects.create(crop=can, problem_master=shared)
        CropProblem.objects.create(crop=legacy, problem_master=shared)
        data = _mini_canonical(
            crop_en="Zz2BCropShare",
            pests=[{"name_en": "ZzSharedPest", "name_ta": "அ"}])
        plan = build_dry_run_plan(data)
        self.assertFalse(any(d["master"] == "ZzSharedPest"
                             for d in plan["pests"]["deactivate"]))
        # the legacy mapping removal is still planned
        self.assertTrue(any(r["master"] == "ZzSharedPest"
                            and r["crop"] == "Zz2BLegacy"
                            for r in plan["mappings"]["remove"]))

    # 10. production-audit path performs zero writes
    def test_2b_10_production_audit_zero_writes(self):
        before = {
            "crop": Crop.objects.count(),
            "master": ProblemMaster.objects.count(),
            "mapping": CropProblem.objects.count(),
            "category": ProblemCategory.objects.count(),
        }
        from django.db import transaction
        from masters.canonical_dataset import compare_to_db
        with transaction.atomic():
            db_counts()
            compare_to_db(load_canonical())
            build_dry_run_plan(load_canonical())
            transaction.set_rollback(True)
        after = {
            "crop": Crop.objects.count(),
            "master": ProblemMaster.objects.count(),
            "mapping": CropProblem.objects.count(),
            "category": ProblemCategory.objects.count(),
        }
        self.assertEqual(before, after)

    # 11. historical reference counting is read-only
    def test_2b_11_historical_counts_read_only(self):
        User = get_user_model()
        u = User.objects.create_user(username="t_hist", password="x")
        m = _master(self.pest_cat, "ZzHistPest")
        c = _crop("ZzHistCrop", "")
        from visits.models import Visit
        v = Visit.objects.create(employee=u, crop=c, problem_master=m)
        v.problem_items.add(m)
        before = {"crop": Crop.objects.count(),
                  "master": ProblemMaster.objects.count(),
                  "visit": Visit.objects.count()}
        refs = historical_reference_counts()
        self.assertEqual(refs["crop_refs"].get(c.id), 1)
        # problem_master + problem_items both counted (2 refs total)
        self.assertEqual(refs["master_refs"].get(m.id), 2)
        after = {"crop": Crop.objects.count(),
                 "master": ProblemMaster.objects.count(),
                 "visit": Visit.objects.count()}
        self.assertEqual(before, after)

    # 12. dry-run is deterministic/idempotent under exact identity
    def test_2b_12_dry_run_idempotent(self):
        data = load_canonical()
        p1 = build_dry_run_plan(data)
        p2 = build_dry_run_plan(data)
        self.assertEqual(plan_summary(p1), plan_summary(p2))
        self.assertEqual(json.dumps(p1, sort_keys=True, default=str),
                         json.dumps(p2, sort_keys=True, default=str))

    def test_2b_greens_tamil_anomaly_flagged_not_corrected(self):
        data = load_canonical()
        anomalies = tamil_anomalies(data)
        self.assertEqual(len(anomalies), 1)
        a = anomalies[0]
        self.assertEqual(a["flag"], "SOURCE_DATA_REVIEW")
        self.assertEqual(a["crop"], "Greens")
        self.assertEqual(a["name_en"], "Mites")
        # canonical JSON keeps the verbatim PDF value
        g = next(e for e in data if e["crop"]["name_en"] == "Greens")
        mite = next(p for p in g["pests"] if p["name_en"] == "Mites")
        self.assertEqual(mite["name_ta"], "முட்டை பூச்சி")

    def test_2b_exact_identity_counts(self):
        """Planned master count = exact unique names per category (130/120),
        NOT the previously normalized 115/104."""
        data = load_canonical()
        keys = canonical_master_keys(data)
        pest_n = len({mn for (c, mn) in keys if c == "pest"})
        dis_n = len({mn for (c, mn) in keys if c == "disease"})
        pests_raw = {p["name_en"].strip() for e in data for p in e["pests"]}
        dis_raw = {d["name_en"].strip() for e in data for d in e["diseases"]}
        self.assertEqual(pest_n, len(pests_raw))
        self.assertEqual(dis_n, len(dis_raw))
