"""Management command for the canonical Crop -> Pest/Disease dataset.

PHASE 2A is deliberately read-only:

    python manage.py canonical_crop_pest_disease --validate
    python manage.py canonical_crop_pest_disease --dry-run

* ``--validate``  validates ``data/crop_pest_disease_canonical.json``
  (structure, Tamil integrity, per-crop duplicates, column independence) and
  prints the duplicate/variant analysis report.  No database access.
* ``--dry-run``   additionally compares the canonical set against the current
  database READ-ONLY and prints the migration plan.  ZERO persistent writes:
  the whole plan is computed from SELECTs only, and is additionally wrapped in
  a rolled-back transaction as a safety net.

Real import mode is intentionally NOT implemented in this phase.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from masters.canonical_dataset import (
    analyze_variants,
    build_dry_run_plan,
    load_canonical,
    plan_summary,
    validate_canonical,
)


class Command(BaseCommand):
    help = "Validate canonical Crop/Pest/Disease JSON and print a dry-run plan (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--validate", action="store_true",
            help="Validate the canonical JSON only (no DB access).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate + compare vs DB read-only and print plan (no writes).")

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
        if not validate and not dry_run:
            self.stderr.write("Specify --validate or --dry-run.")
            return

        data = load_canonical()
        rep = validate_canonical(data)
        self._print_validation(rep, data)

        if dry_run:
            # Safety net: compute the entire plan inside a transaction that we
            # force to roll back.  build_dry_run_plan performs no writes anyway.
            with transaction.atomic():
                plan = build_dry_run_plan(data)
                transaction.set_rollback(True)
            self._print_plan(plan)

        if not rep.ok:
            # Non-zero signal that validation failed (but still printed report).
            self.stderr.write("VALIDATION FAILED -- see errors above.")
            raise SystemExit(1)

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

    def _print_plan(self, plan):
        out = self.stdout
        s = plan_summary(plan)
        out.write("=" * 70)
        out.write("DRY-RUN MIGRATION PLAN  (ZERO writes performed)")
        out.write("=" * 70)
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
        out.write("\n[AMBIGUOUS -- manual approval required]")
        for it in plan["ambiguous"]:
            out.write(f"      {it}")
        if not plan["ambiguous"]:
            out.write("      (none)")
        out.write("\nSUMMARY")
        out.write(json.dumps(s, indent=2))
        out.write("")
