"""Management command for the canonical Crop -> Pest/Disease dataset.

    python manage.py canonical_crop_pest_disease --validate
    python manage.py canonical_crop_pest_disease --dry-run
    python manage.py canonical_crop_pest_disease --production-audit
    python manage.py canonical_crop_pest_disease --apply

* ``--validate``  validates ``data/crop_pest_disease_canonical.json``
  (structure, Tamil integrity, per-crop duplicates, column independence) and
  prints the duplicate/variant analysis report.  No database access.
* ``--dry-run``   additionally compares the canonical set against the current
  database READ-ONLY and prints the migration plan.  ZERO persistent writes.
* ``--production-audit``  is the production preflight mode intended to be run
  ON the production server (it audits whichever DATABASE the process connects
  to).  It prints actual table counts, the full canonical-vs-database
  classification, the historical-reference audit and the complete plan.
  Identical code path to ``--dry-run`` -- SELECTs only, PLUS an explicit
  force-rolled-back transaction as a safety net.
* ``--apply``     PHASE 3B real import.  Refuses unless every safety gate
  passes (canonical validation OK, categories exist, no ambiguous canonical
  crop, source duplicates collapse).  Everything runs inside a single
  ``transaction.atomic()`` -- any failure rolls back completely.  Never
  hard-deletes; never touches Visit rows.  Legacy duplicate masters are
  inactivated but never reused -- canonical masters carry
  ``is_canonical=True`` (created fresh or adopted single exact match).

Identity rule (Phase 2B): a canonical ProblemMaster is
``category + EXACT PDF English value`` (whitespace-trimmed only).  Case,
spacing and spelling variants are preserved as DISTINCT candidates and are
never auto-merged.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from masters.canonical_dataset import (
    ApplyGateError,
    analyze_variants,
    apply_gates,
    apply_import,
    build_dry_run_plan,
    compare_to_db,
    db_counts,
    load_canonical,
    plan_summary,
    validate_canonical,
)


class Command(BaseCommand):
    help = "Validate canonical Crop/Pest/Disease JSON and print a read-only audit / dry-run plan."

    def add_arguments(self, parser):
        parser.add_argument(
            "--validate", action="store_true",
            help="Validate the canonical JSON only (no DB access).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate + compare vs DB read-only and print plan (no writes).")
        parser.add_argument(
            "--production-audit", action="store_true",
            help="Production preflight: actual counts + classification + plan. "
                 "Run on the production server. ZERO writes.")
        parser.add_argument(
            "--apply", action="store_true",
            help="PHASE 3B real import. Refuses unless all safety gates pass. "
                 "Single transaction; never hard-deletes; never touches "
                 "Visit rows.  Legacy duplicate masters are inactivated, "
                 "never reused -- canonical masters are marked "
                 "is_canonical or created fresh.")
        parser.add_argument(
            "--canonical-file", type=str, default=None,
            help="Override canonical JSON path (default: data/"
                 "crop_pest_disease_canonical.json).")

    def handle(self, *args, **options):
        # The plan/validation output contains Unicode Tamil.  Reconfigure the
        # console to UTF-8 so it can be printed regardless of the host codepage
        # (Windows consoles default to cp1252 and would crash).
        try:
            self.stdout._out.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        validate = options["validate"]
        dry_run = options["dry_run"]
        prod_audit = options["production_audit"]
        apply_mode = options["apply"]
        if not validate and not dry_run and not prod_audit and not apply_mode:
            self.stderr.write(
                "Specify --validate, --dry-run, --production-audit or --apply.")
            return

        data = load_canonical(options["canonical_file"])
        rep = validate_canonical(data)
        self._print_validation(rep, data)

        if dry_run or prod_audit:
            # Safety net: everything runs inside a transaction that we force
            # to roll back.  All plan/comparison code is SELECT-only anyway.
            with transaction.atomic():
                counts = db_counts()
                comparison = compare_to_db(data)
                plan = build_dry_run_plan(data)
                transaction.set_rollback(True)
            if prod_audit:
                self._print_production_counts(counts)
            self._print_comparison(comparison)
            self._print_plan(plan)

        if apply_mode:
            self._run_apply(data)

        if not rep.ok:
            # Non-zero signal that validation failed (but still printed report).
            self.stderr.write("VALIDATION FAILED -- see errors above.")
            raise SystemExit(1)

    # ------------------------------------------------------------------
    def _run_apply(self, data):
        out = self.stdout
        out.write("=" * 70)
        out.write("APPLY SAFETY GATES")
        out.write("=" * 70)
        errors = apply_gates(data)
        if errors:
            for e in errors:
                out.write(f"  GATE FAIL  {e}")
            self.stderr.write(
                f"APPLY REFUSED: {len(errors)} gate failure(s). "
                "No writes performed.")
            raise SystemExit(1)
        out.write("  all gates passed")
        try:
            stats = apply_import(data)
        except ApplyGateError as exc:
            for e in exc.errors:
                self.stderr.write(f"  GATE FAIL  {e}")
            self.stderr.write(
                "APPLY REFUSED inside transaction -- zero writes persisted.")
            raise SystemExit(1)
        out.write("\nAPPLY RESULT")
        for k, v in stats.items():
            if k == "tamil_diffs_kept":
                out.write(f"  {k}: {len(v)}")
                for it in v[:50]:
                    out.write(f"      {it}")
            else:
                out.write(f"  {k}: {v}")
        out.write("APPLY COMPLETE -- single transaction committed.")

    # ------------------------------------------------------------------
    def _print_validation(self, rep, data):
        out = self.stdout
        out.write("=" * 70)
        out.write("CANONICAL DATASET VALIDATION")
        out.write("=" * 70)
        out.write(f"crops: {len(data)}")
        tp = sum(len(e.get("pests", [])) for e in data)
        td = sum(len(e.get("diseases", [])) for e in data)
        out.write(f"pest associations: {tp}")
        out.write(f"disease associations: {td}")
        out.write(f"ERRORS: {len(rep.errors)}")
        for e in rep.errors:
            out.write(f"  ERROR  {e}")
        out.write(f"TAMIL_REVIEW_REQUIRED: {len(rep.tamil_review_required)}")
        for t in rep.tamil_review_required:
            out.write(f"  REVIEW {t}")
        out.write(f"BLANK_TAMIL (genuinely blank in PDF): {len(rep.blank_tamil)}")
        for t in rep.blank_tamil:
            out.write(f"  BLANK  {t}")
        out.write(f"DUPLICATES WITHIN CROP: {len(rep.duplicates_within_crop)}")
        for t in rep.duplicates_within_crop:
            out.write(f"  DUP    {t}")
        out.write(f"SUSPECT CROSS-COLUMN: {len(rep.suspect_cross_column)}")
        for t in rep.suspect_cross_column:
            out.write(f"  XCOL   {t}")

        variants = analyze_variants(data)
        out.write("\nVARIANT / DUPLICATE ANALYSIS (report only -- NOT merged)")
        for kind in ("pest", "disease"):
            v = variants[kind]
            out.write(f"\n[{kind.upper()}]")
            out.write(f"  exact shared masters (same name, >1 crop): "
                      f"{len(v['exact_shared_masters'])}")
            out.write(f"  case-only variants: {len(v['case_only_variants'])}")
            for g in v["case_only_variants"]:
                out.write(f"      {g['variants']} on {g['crops']}")
            out.write(f"  spacing variants: {len(v['spacing_variants'])}")
            for g in v["spacing_variants"]:
                out.write(f"      {g}")
            out.write(f"  spelling variants: {len(v['spelling_variants'])}")
            for g in v["spelling_variants"]:
                out.write(f"      {g}")
            out.write(f"  possible semantic duplicates: "
                      f"{len(v['possible_semantic_duplicates'])}")
            for g in v["possible_semantic_duplicates"]:
                out.write(f"      {g}")
        out.write("")

    # ------------------------------------------------------------------
    def _print_production_counts(self, counts):
        out = self.stdout
        out.write("=" * 70)
        out.write("DATABASE COUNTS  (read-only snapshot)")
        out.write("=" * 70)
        for k, v in counts.items():
            out.write(f"  {k:26s} {v}")
        out.write("")

    def _print_comparison(self, cmp_):
        out = self.stdout
        out.write("=" * 70)
        out.write("CANONICAL-vs-DB CLASSIFICATION  (exact PDF identity)")
        out.write("=" * 70)
        c = cmp_["crops"]
        out.write("CROPS:")
        out.write(f"  CANONICAL_EXACT          {len(c['canonical_exact'])}")
        out.write(f"  CANONICAL_UPDATE_REQUIRED {len(c['update_required'])}")
        out.write(f"  CANONICAL_MISSING        {len(c['canonical_missing'])}")
        out.write(f"  LEGACY_PRODUCTION_ONLY   {len(c['legacy_only'])}")
        out.write(f"  AMBIGUOUS                {len(c['ambiguous'])}")
        m = cmp_["masters"]
        out.write("PROBLEM MASTERS:")
        out.write(f"  EXACT_REUSABLE             {len(m['exact_reusable'])}")
        out.write(f"  CANONICAL_MISSING          {len(m['canonical_missing'])}")
        out.write(f"  LEGACY_PRODUCTION_ONLY     {len(m['legacy_only'])}")
        out.write(f"  VARIANT_REQUIRES_APPROVAL  {len(m['variant_requires_approval'])}")
        out.write(f"  NON_CROP_HEALTH            {len(m['non_crop_health'])}")
        out.write(f"  AMBIGUOUS                  {len(m['ambiguous'])}")
        mp = cmp_["mappings"]
        out.write("MAPPINGS:")
        out.write(f"  CANONICAL_EXISTS      {len(mp['exists'])}")
        out.write(f"  CANONICAL_MISSING     {len(mp['missing'])}")
        out.write(f"  LEGACY_NONCANONICAL   {len(mp['legacy_noncanonical'])}")
        out.write(f"  AMBIGUOUS             {len(mp['ambiguous'])}")
        cats = cmp_["categories"]
        out.write("CATEGORIES:")
        out.write(f"  pest    id={cats['pest_id']} active={cats['pest_active']}")
        out.write(f"  disease id={cats['disease_id']} active={cats['disease_active']}")
        out.write("")

    # ------------------------------------------------------------------
    def _print_plan(self, plan):
        out = self.stdout
        s = plan_summary(plan)
        out.write("=" * 70)
        out.write("DRY-RUN MIGRATION PLAN  (ZERO writes performed)")
        out.write("=" * 70)

        out.write("\n[CATEGORIES]")
        for code, c in plan["categories"].items():
            out.write(f"  {code:8s} -> {c}")

        for section in ("crops", "pests", "diseases", "mappings"):
            out.write(f"\n[{section.upper()}]")
            for action, items in plan[section].items():
                out.write(f"  {action:10s} {len(items)}")
                for it in items[:50]:
                    out.write(f"      {it}")

        out.write("\n[HISTORY -- referenced legacy records preserved]")
        for it in plan["history"]["referenced_legacy"][:80]:
            out.write(f"      {it}")
        if not plan["history"]["referenced_legacy"]:
            out.write("      (none referenced)")

        out.write("\n[REVIEW ITEMS -- approval required before real import]")
        rv = plan.get("review_items", {})
        sd = rv.get("source_duplicates", {})
        out.write(f"  source_duplicates: {sd.get('count', 0)}  "
                  f"planned_duplicate_db_mappings: "
                  f"{sd.get('planned_db_mappings', 0)}")
        for it in sd.get("items", []):
            out.write(f"      {it}")
        out.write(f"  tamil_source_anomalies: "
                  f"{len(rv.get('tamil_source_anomalies', []))}")
        for it in rv.get("tamil_source_anomalies", []):
            out.write(f"      {it}")
        cv = rv.get("case_variants", {})
        out.write(f"  case_variants preserved separately: "
                  f"pest={len(cv.get('pest', []))} "
                  f"disease={len(cv.get('disease', []))}")
        sv = rv.get("spelling_variants", {})
        out.write(f"  spelling_variants reported (not merged): "
                  f"pest={len(sv.get('pest', []))} "
                  f"disease={len(sv.get('disease', []))}")

        out.write("\n[AMBIGUOUS -- manual approval required]")
        for it in plan["ambiguous"]:
            out.write(f"      {it}")
        if not plan["ambiguous"]:
            out.write("      (none)")
        out.write("\nSUMMARY")
        out.write(json.dumps(s, indent=2))
        out.write("")
