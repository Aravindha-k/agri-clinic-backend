"""Canonical Crop -> Pest/Disease dataset utilities.

PHASE 2A: the original PDF "Pest & Diseases Final - Final.pdf" is the ONLY
business-data source.  The canonical JSON at
``data/crop_pest_disease_canonical.json`` was transcribed by rendering each
PDF page visually (embedded Tamil fonts make raw text extraction unreliable)
and reading the visible tables.  This module:

* loads and VALIDATES the canonical JSON (structural + Tamil integrity)
* analyses duplicate / variant English names (no auto-merge)
* compares the canonical set READ-ONLY against the current database
* builds a DRY-RUN migration plan (zero persistent writes)

Nothing in this module writes to the database.  ``build_dry_run_plan`` and
``compare_to_db`` only read.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from django.conf import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANONICAL_PATH = Path(settings.BASE_DIR) / "data" / "crop_pest_disease_canonical.json"
TAMIL_REVIEW_REQUIRED = "TAMIL_REVIEW_REQUIRED"

PEST = "pest"
DISEASE = "disease"
CROP_HEALTH_CODES = (PEST, DISEASE)

# Tamil Unicode block.  Valid transcribed Tamil is composed ONLY of this block
# plus a small set of separators we saw rendered in the PDF (space, slash,
# parentheses, hyphen, dot, comma, apostrophe).
_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_ALLOWED_SEPARATORS = set(" \t/\\()-.,'’&+")
# Markers that indicate corrupted embedded-font extraction that must never
# enter the canonical dataset.
_CORRUPTION_MARKERS = ("(cid:", "\ufffd", "\\x")

# English words that strongly indicate a *disease* row (used only to FLAG
# suspect cross-contamination for manual review -- never auto-corrected).
_DISEASE_TOKENS = {
    "disease", "rot", "blight", "spot", "wilt", "mildew", "mosaic", "rust",
    "canker", "mould", "smut", "necrosis", "streak", "scab", "gummosis",
    "decline", "gall", "phyllody", "crinkle", "curl", "blotch", "stunt",
    "bakanae", "tungro", "bleeding", "boeng", "ergot", "blast", "damping",
}
# English words that strongly indicate a *pest* row.
_PEST_TOKENS = {
    "borer", "beetle", "aphid", "caterpillar", "fly", "bug", "moth", "worm",
    "mite", "weevil", "hopper", "scale", "termite", "grub", "maggot",
    "whitefly", "thrips", "butterfly", "grasshopper", "ant", "bee", "snail",
    "midge", "mealybug", "pyrilla", "hispa", "leafminer", "miner", "armyworm",
    "bollworm", "leafhopper", "jassid", "webber", "web", "budworm", "piercing",
    "roller", "folder", "leaf", "pod", "stem", "shoot", "earhead", "bud",
}
# NOTE: _PEST_TOKENS/_DISEASE_TOKENS intentionally overlap a little (e.g.
# "leaf", "stem", "bud", "pod" appear in both).  Cross-contamination is only
# flagged when a name matches the *opposite* list and NOT its own.

# Curated misspellings observed in the source PDF (never auto-applied -- they
# are only surfaced in the variant report for human approval).
_KNOWN_MISSPELLINGS = {
    "bettle": "beetle",
    "thirps": "thrips",
    "caterpilar": "caterpillar",
    "catterpillar": "caterpillar",
    "meally": "mealy",
    "meallybug": "mealybug",
    "alterneria": "alternaria",
    "bactertial": "bacterial",
    "powdry": "powdery",
    "bettle": "beetle",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_canonical(path: Optional[Path] = None):
    """Load the canonical JSON.  Raises on invalid JSON."""
    p = Path(path) if path else CANONICAL_PATH
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_items(crop_entry: dict, kind: str) -> Iterable[dict]:
    """Yield pest/disease item dicts for a crop entry."""
    yield from crop_entry.get(kind, [])


# ---------------------------------------------------------------------------
# Tamil integrity
# ---------------------------------------------------------------------------

def is_valid_tamil_value(value) -> bool:
    """Return True when *value* is an acceptable Tamil field.

    Acceptable:
    * verified Unicode Tamil (contains >=1 char in the Tamil block and only
      Tamil + allowed separator characters)
    * empty string -- a value genuinely blank in the PDF
    * the literal ``TAMIL_REVIEW_REQUIRED`` sentinel
    """
    if not isinstance(value, str):
        return False
    if value == TAMIL_REVIEW_REQUIRED:
        return True
    if value == "":
        return True
    low = value.lower()
    for marker in _CORRUPTION_MARKERS:
        if marker in low or marker in value:
            return False
    has_tamil = False
    for ch in value:
        if _TAMIL_RE.match(ch):
            has_tamil = True
            continue
        if ch in _ALLOWED_SEPARATORS:
            continue
        # allow ASCII letters/digits only inside parenthesised latin abbrev.
        if ch.isascii() and (ch.isalpha() or ch.isdigit()):
            # e.g. transliterated tokens are not expected; treat latin as
            # suspect unless wrapped -- keep strict: latin => invalid
            return False
        return False
    return has_tamil


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    errors: list = field(default_factory=list)          # hard failures
    warnings: list = field(default_factory=list)        # review items
    tamil_review_required: list = field(default_factory=list)
    blank_tamil: list = field(default_factory=list)
    duplicates_within_crop: list = field(default_factory=list)
    suspect_cross_column: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _tokens(english: str) -> set:
    return set(re.findall(r"[a-z]+", (english or "").lower()))


def validate_canonical(data) -> ValidationReport:
    rep = ValidationReport()
    if not isinstance(data, list):
        rep.errors.append("canonical root must be a list")
        return rep
    seen_crop_seq = set()
    for idx, entry in enumerate(data):
        ctx = f"crop[{idx}]"
        if not isinstance(entry, dict):
            rep.errors.append(f"{ctx}: not an object")
            continue
        crop = entry.get("crop") or {}
        name_en = (crop.get("name_en") or "").strip()
        name_ta = (crop.get("name_ta") or "")
        seq = entry.get("seq")
        if seq in seen_crop_seq:
            rep.errors.append(f"{ctx}: duplicate seq {seq}")
        seen_crop_seq.add(seq)
        if not name_en:
            rep.errors.append(f"{ctx}: crop name_en blank")
        if not is_valid_tamil_value(name_ta):
            rep.errors.append(f"{ctx} {name_en}: crop Tamil corrupted {name_ta!r}")
        if name_ta == TAMIL_REVIEW_REQUIRED:
            rep.tamil_review_required.append(f"{ctx} {name_en} (crop)")
        if name_ta == "":
            rep.blank_tamil.append(f"{ctx} {name_en} (crop)")
        pests = entry.get("pests")
        diseases = entry.get("diseases")
        if not isinstance(pests, list) or not isinstance(diseases, list):
            rep.errors.append(f"{ctx} {name_en}: pests/diseases must be lists")
            continue
        for kind, items in (("pests", pests), ("diseases", diseases)):
            seen_names = set()
            for it in items:
                en = (it.get("name_en") or "").strip()
                ta = it.get("name_ta") or ""
                tag = f"{ctx} {name_en} {kind[:-1]} {en!r}"
                if not en:
                    rep.errors.append(f"{tag}: name_en blank")
                if not is_valid_tamil_value(ta):
                    rep.errors.append(f"{tag}: Tamil corrupted {ta!r}")
                if ta == TAMIL_REVIEW_REQUIRED:
                    rep.tamil_review_required.append(tag)
                if ta == "":
                    rep.blank_tamil.append(tag)
                key = en.lower()
                if key in seen_names:
                    rep.duplicates_within_crop.append(f"{tag}: duplicate within crop")
                seen_names.add(key)
                # cross-column heuristic -- flag for review only
                toks = _tokens(en)
                if kind == "pests":
                    if toks & _DISEASE_TOKENS and not toks & _PEST_TOKENS:
                        rep.suspect_cross_column.append(
                            f"{tag}: looks like a disease inside pests")
                else:
                    if toks & _PEST_TOKENS and not toks & _DISEASE_TOKENS:
                        rep.suspect_cross_column.append(
                            f"{tag}: looks like a pest inside diseases")
    return rep


# ---------------------------------------------------------------------------
# Variant / duplicate analysis (report only -- no merging)
# ---------------------------------------------------------------------------

def _norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _squash(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").lower())


def analyze_variants(data) -> dict:
    """Group English names per issue-type into variant buckets.

    Returns dict with keys exact, case_only, spacing, spelling, semantic.
    All values are lists of groups (each group a list of raw names + crops).
    Nothing is merged -- this is a review report.
    """
    # collect name -> set(crop) per kind
    names = {PEST: {}, DISEASE: {}}  # normkey -> {"variants":set, "crops":set}
    display = {PEST: {}, DISEASE: {}}
    for entry in data:
        crop_en = (entry.get("crop") or {}).get("name_en") or "?"
        for kind, key in (("pests", PEST), ("diseases", DISEASE)):
            for it in entry.get(kind, []):
                en = (it.get("name_en") or "").strip()
                if not en:
                    continue
                nk = _norm_key(en)
                slot = names[key].setdefault(
                    nk, {"variants": set(), "crops": set(), "orig": en})
                slot["variants"].add(en)
                slot["crops"].add(crop_en)
                display[key][nk] = slot

    def _similar(a, b):
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio()

    result = {}
    for kind in (PEST, DISEASE):
        exact = []          # same normkey used by >1 crop (shared master)
        case_only = []      # normkey->multiple raw spellings differing by case
        spacing = []        # different squash-grouped
        spelling = []
        semantic = []
        by_squash = {}
        for nk, slot in names[kind].items():
            variants = slot["variants"]
            if len(slot["crops"]) > 1:
                exact.append({"name": slot["orig"], "crops": sorted(slot["crops"])})
            if len(variants) > 1:
                # same normkey differing only in case
                lowers = {v.lower() for v in variants}
                if len(lowers) == 1:
                    case_only.append({"name": slot["orig"],
                                      "variants": sorted(variants),
                                      "crops": sorted(slot["crops"])})
            by_squash.setdefault(_squash(nk), []).append((nk, slot))
        for sq, slots in by_squash.items():
            if len(slots) > 1:
                spacing.append([s[1]["orig"] for s in slots])
        # spelling variants via curated map + fuzzy ratio
        keys = list(names[kind].keys())
        flagged = set()
        for i, a in enumerate(keys):
            for b in keys[i+1:]:
                if (a, b) in flagged:
                    continue
                ra = _similar(a, b)
                sa, sb = a.split(), b.split()
                # curated misspelling: one token is a known misspelling of the
                # *other* token (not just any misspelled token vs anything).
                spell_hit = False
                if len(sa) == len(sb):
                    diffs = [(x, y) for x, y in zip(sa, sb) if x != y]
                    if len(diffs) == 1:
                        x, y = diffs[0]
                        if _KNOWN_MISSPELLINGS.get(x) == y or \
                           _KNOWN_MISSPELLINGS.get(y) == x:
                            spell_hit = True
                if not spell_hit and 0.78 < ra < 1.0:
                    spell_hit = True
                if spell_hit:
                    spelling.append(
                        [names[kind][a]["orig"], names[kind][b]["orig"]])
                    flagged.add((a, b))
                elif 0.60 < ra <= 0.78:
                    semantic.append(
                        [names[kind][a]["orig"], names[kind][b]["orig"]])
        result[kind] = {
            "exact_shared_masters": exact,
            "case_only_variants": case_only,
            "spacing_variants": spacing,
            "spelling_variants": spelling,
            "possible_semantic_duplicates": semantic,
        }
    return result


# ---------------------------------------------------------------------------
# Read-only database comparison
# ---------------------------------------------------------------------------

def _db_models():
    from masters.models import Crop, ProblemCategory, ProblemMaster, CropProblem
    return Crop, ProblemCategory, ProblemMaster, CropProblem


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def compare_to_db(data=None) -> dict:
    """READ-ONLY comparison of canonical data against current DB rows.

    Returns a classification dict; performs zero writes.
    """
    Crop, ProblemCategory, ProblemMaster, CropProblem = _db_models()
    if data is None:
        data = load_canonical()

    db_crops = list(Crop.objects.all())
    db_crops_by_norm = {}
    for c in db_crops:
        db_crops_by_norm.setdefault(_norm(c.name_en).lower(), []).append(c)

    # --- crops ---
    canon_crop_norms = set()
    crop_cmp = {"exact": [], "name_update": [], "missing_db": [],
                "ambiguous": []}
    for entry in data:
        en = _norm(entry["crop"]["name_en"])
        ta = _norm(entry["crop"]["name_ta"])
        canon_crop_norms.add(en.lower())
        hits = db_crops_by_norm.get(en.lower(), [])
        if len(hits) == 1:
            db = hits[0]
            if _norm(db.name_ta) != ta:
                crop_cmp["name_update"].append(
                    {"crop": en, "db_id": db.id, "db_ta": db.name_ta,
                     "canon_ta": ta})
            else:
                crop_cmp["exact"].append({"crop": en, "db_id": db.id})
        elif len(hits) > 1:
            crop_cmp["ambiguous"].append(
                {"crop": en, "candidates": [h.id for h in hits]})
        else:
            crop_cmp["missing_db"].append({"crop": en, "canon_ta": ta})
    canonical_set = { _norm(e["crop"]["name_en"]).lower() for e in data }
    legacy_db_only = [c for c in db_crops
                      if _norm(c.name_en).lower() not in canonical_set]
    crop_cmp["legacy_db_only"] = [{"crop": c.name_en, "db_id": c.id,
                                   "is_active": c.is_active}
                                  for c in legacy_db_only]

    # --- problem masters ---
    cat_by_code = {pc.code: pc for pc in ProblemCategory.objects.all()}
    pest_cat = cat_by_code.get(PEST)
    disease_cat = cat_by_code.get(DISEASE)
    db_masters = list(ProblemMaster.objects.select_related("category", "crop"))
    masters_by_cat_name = {}
    for m in db_masters:
        code = m.category.code if m.category_id else None
        masters_by_cat_name.setdefault((code, _norm(m.name).lower()), []).append(m)

    master_cmp = {"reusable_exact": [], "variant": [], "missing_db": [],
                  "ambiguous": []}
    canonical_master_keys = set()   # (code, normname)
    canonical_master_usage = {}     # (code,normname) -> set(crop norms)
    for entry in data:
        cen = _norm(entry["crop"]["name_en"]).lower()
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            for it in entry.get(kind, []):
                mn = _norm(it["name_en"])
                key = (code, mn.lower())
                canonical_master_keys.add(key)
                canonical_master_usage.setdefault(key, set()).add(cen)
    for code, mn_lower in sorted(canonical_master_keys):
        hits = masters_by_cat_name.get((code, mn_lower), [])
        disp = mn_lower
        # find display name
        for e in data:
            for kind, cc in (("pests", PEST), ("diseases", DISEASE)):
                if cc == code:
                    for it in e.get(kind, []):
                        if _norm(it["name_en"]).lower() == mn_lower:
                            disp = it["name_en"]
        if len(hits) == 1:
            m = hits[0]
            # exact -> check tamil matches; else variant
            if _norm(m.tamil_name) and _norm(m.tamil_name) != "" and \
               _norm(m.tamil_name) != _norm(_find_ta(data, code, m.name)):
                master_cmp["variant"].append(
                    {"master": disp, "db_id": m.id, "reason": "tamil differs",
                     "db_ta": m.tamil_name})
            else:
                master_cmp["reusable_exact"].append(
                    {"master": disp, "db_id": m.id})
        elif len(hits) > 1:
            master_cmp["ambiguous"].append(
                {"master": disp, "candidates": [h.id for h in hits]})
        else:
            # look for variant (case/spacing/spelling) within same category
            cand = _find_master_variant(db_masters, code, mn_lower)
            if cand:
                master_cmp["variant"].append(
                    {"master": disp, "candidates": [
                        {"db_id": c.id, "name": c.name} for c in cand],
                     "reason": "near-name variant"})
            else:
                master_cmp["missing_db"].append({"master": disp, "code": code})
    legacy_masters = [m for m in db_masters
                      if (m.category.code if m.category_id else None)
                      in CROP_HEALTH_CODES
                      and (m.category.code, _norm(m.name).lower())
                      not in canonical_master_keys]
    non_crop_health = [m for m in db_masters
                       if (m.category.code if m.category_id else None)
                       not in CROP_HEALTH_CODES]
    master_cmp["legacy_db_only"] = [
        {"master": m.name, "db_id": m.id,
         "code": m.category.code if m.category_id else None,
         "is_active": m.is_active} for m in legacy_masters]
    master_cmp["non_crop_health"] = [
        {"master": m.name, "db_id": m.id,
         "code": m.category.code if m.category_id else None}
        for m in non_crop_health]

    # --- mappings ---
    db_mappings = list(CropProblem.objects.select_related(
        "crop", "problem_master", "problem_master__category"))
    db_map_keys = set()
    for cp in db_mappings:
        cn = _norm(cp.crop.name_en).lower()
        code = cp.problem_master.category.code if cp.problem_master.category_id else None
        mn = _norm(cp.problem_master.name).lower()
        db_map_keys.add((cn, code, mn))
    mapping_cmp = {"exists": [], "missing": [], "legacy_not_canonical": []}
    canonical_map_keys = set()
    for entry in data:
        cn = _norm(entry["crop"]["name_en"]).lower()
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            for it in entry.get(kind, []):
                canonical_map_keys.add((cn, code, _norm(it["name_en"]).lower()))
    for k in sorted(canonical_map_keys):
        (mapping_cmp["exists"] if k in db_map_keys
         else mapping_cmp["missing"]).append(
            {"crop": k[0], "code": k[1], "master": k[2]})
    for k in db_map_keys:
        if k not in canonical_map_keys:
            mapping_cmp["legacy_not_canonical"].append(
                {"crop": k[0], "code": k[1], "master": k[2]})

    return {"crops": crop_cmp, "masters": master_cmp,
            "mappings": mapping_cmp,
            "categories": {"pest_id": getattr(pest_cat, "id", None),
                           "pest_active": getattr(pest_cat, "is_active", None),
                           "disease_id": getattr(disease_cat, "id", None),
                           "disease_active": getattr(disease_cat, "is_active", None)}}


def _find_ta(data, code, name):
    for e in data:
        for kind, cc in (("pests", PEST), ("diseases", DISEASE)):
            if cc != code:
                continue
            for it in e.get(kind, []):
                if _norm(it["name_en"]).lower() == _norm(name).lower():
                    return it.get("name_ta") or ""
    return ""


def _find_master_variant(db_masters, code, mn_lower):
    """Near-name candidates in the same category (case/spacing/spelling)."""
    import difflib
    out = []
    for m in db_masters:
        mcode = m.category.code if m.category_id else None
        if mcode != code:
            continue
        mn = _norm(m.name).lower()
        if mn == mn_lower:
            continue
        if _squash(mn) == _squash(mn_lower) or \
           difflib.SequenceMatcher(None, mn, mn_lower).ratio() > 0.8:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Historical reference check (read-only)
# ---------------------------------------------------------------------------

def historical_reference_counts() -> dict:
    """Count Visit references to each Crop and ProblemMaster.  READ-ONLY."""
    from visits.models import Visit
    Crop, ProblemCategory, ProblemMaster, CropProblem = _db_models()
    crop_refs = {}
    master_refs = {}
    for v in Visit.objects.only("crop_id", "problem_master_id"):
        if v.crop_id:
            crop_refs[v.crop_id] = crop_refs.get(v.crop_id, 0) + 1
        if v.problem_master_id:
            master_refs[v.problem_master_id] = \
                master_refs.get(v.problem_master_id, 0) + 1
    # M2M problem_items
    try:
        through = Visit.problem_items.through
        for row in through.objects.values_list("visit_id", "problemmaster_id"):
            pid = row[1]
            if pid:
                master_refs[pid] = master_refs.get(pid, 0) + 1
    except Exception:
        pass
    return {"crop_refs": crop_refs, "master_refs": master_refs}


# ---------------------------------------------------------------------------
# Dry-run plan builder (pure reads + computed plan; ZERO writes)
# ---------------------------------------------------------------------------

def build_dry_run_plan(data=None) -> dict:
    """Compute the migration plan WITHOUT writing anything.

    Returns a structured plan describing would-be creates/updates/keeps/
    deactivations/removals and historical-preservation notes.  The caller
    (management command / tests) may wrap invocation in a transaction that is
    rolled back; this function itself performs no ORM writes at all.
    """
    Crop, ProblemCategory, ProblemMaster, CropProblem = _db_models()
    if data is None:
        data = load_canonical()
    cmp_ = compare_to_db(data)
    refs = historical_reference_counts()

    db_crops = {_norm(c.name_en).lower(): c for c in Crop.objects.all()}
    db_masters = {}
    for m in ProblemMaster.objects.select_related("category"):
        code = m.category.code if m.category_id else None
        db_masters.setdefault((code, _norm(m.name).lower()), []).append(m)
    db_map = set()
    for cp in CropProblem.objects.select_related("crop", "problem_master__category"):
        db_map.add((_norm(cp.crop.name_en).lower(),
                    cp.problem_master.category.code if cp.problem_master.category_id else None,
                    _norm(cp.problem_master.name).lower()))
    existing_map_objs = {}
    for cp in CropProblem.objects.select_related("crop", "problem_master__category"):
        existing_map_objs[(_norm(cp.crop.name_en).lower(),
                           cp.problem_master.category.code if cp.problem_master.category_id else None,
                           _norm(cp.problem_master.name).lower())] = cp.id

    plan = {
        "crops": {"create": [], "update": [], "keep": [], "deactivate": []},
        "pests": {"create": [], "reuse": [], "review": [], "deactivate": []},
        "diseases": {"create": [], "reuse": [], "review": [], "deactivate": []},
        "mappings": {"create": [], "keep": [], "remove": []},
        "history": {"referenced_legacy": []},
        "ambiguous": [],
    }

    # crops
    canonical_crop_keys = set()
    for e in data:
        en = _norm(e["crop"]["name_en"])
        ta = _norm(e["crop"]["name_ta"])
        canonical_crop_keys.add(en.lower())
        db = db_crops.get(en.lower())
        if db is None:
            plan["crops"]["create"].append({"crop": en, "name_ta": ta})
        else:
            if _norm(db.name_ta) != ta:
                plan["crops"]["update"].append(
                    {"crop": en, "db_id": db.id, "from_ta": db.name_ta, "to_ta": ta})
            else:
                plan["crops"]["keep"].append({"crop": en, "db_id": db.id})
            if not db.is_active:
                plan["crops"]["update"].append(
                    {"crop": en, "db_id": db.id, "reactivate": True})
    for c in Crop.objects.all():
        if _norm(c.name_en).lower() not in canonical_crop_keys:
            refc = refs["crop_refs"].get(c.id, 0)
            plan["crops"]["deactivate"].append(
                {"crop": c.name_en, "db_id": c.id, "visit_refs": refc,
                 "preserve": "kept inactive; never hard-deleted"})
            if refc:
                plan["history"]["referenced_legacy"].append(
                    {"type": "crop", "name": c.name_en, "db_id": c.id,
                     "visit_refs": refc})

    # masters -- canonical usage per (code,name)
    canonical_master_keys = set()
    canonical_master_crops = {}
    for e in data:
        cn = _norm(e["crop"]["name_en"]).lower()
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            for it in e.get(kind, []):
                key = (code, _norm(it["name_en"]).lower())
                canonical_master_keys.add(key)
                canonical_master_crops.setdefault(key, set()).add(cn)

    # which canonical masters map to db rows
    def _master_plan_entry(code, key):
        hits = db_masters.get(key, [])
        if len(hits) == 1:
            return ("reuse", hits[0])
        if len(hits) > 1:
            return ("review", hits)
        cand = _find_master_variant(
            list(ProblemMaster.objects.select_related("category")), code, key[1])
        if cand:
            return ("review", cand)
        return ("create", None)

    for code, mn in sorted(canonical_master_keys):
        slot = "pests" if code == PEST else "diseases"
        hits = db_masters.get((code, mn), [])
        if len(hits) == 1:
            plan[slot]["reuse"].append({"master": hits[0].name, "db_id": hits[0].id})
        elif len(hits) > 1:
            plan[slot]["review"].append(
                {"master": mn, "candidates": [h.id for h in hits],
                 "reason": "multiple db rows match"})
            plan["ambiguous"].append(
                {"type": "master", "name": mn, "code": code,
                 "candidates": [h.id for h in hits]})
        else:
            cand = _find_master_variant(
                list(ProblemMaster.objects.select_related("category")), code, mn)
            if cand:
                plan[slot]["review"].append(
                    {"master": mn, "candidates": [
                        {"db_id": c.id, "name": c.name} for c in cand],
                     "reason": "near-name variant requires decision"})
            else:
                plan[slot]["create"].append({"master": mn, "code": code})

    # legacy masters (pest/disease category not used canonically) -> deactivate
    for m in ProblemMaster.objects.select_related("category"):
        code = m.category.code if m.category_id else None
        if code not in CROP_HEALTH_CODES:
            continue
        key = (code, _norm(m.name).lower())
        if key in canonical_master_keys:
            continue
        refc = refs["master_refs"].get(m.id, 0)
        entry = {"master": m.name, "db_id": m.id, "code": code,
                 "visit_refs": refc}
        # shared-master safety: only deactivate if NO canonical crop uses it;
        # since it isn't a canonical master at all, it is a deactivate cand.
        plan["pests" if code == PEST else "diseases"]["deactivate"].append(entry)
        if refc:
            plan["history"]["referenced_legacy"].append(
                {"type": "master", "name": m.name, "db_id": m.id,
                 "visit_refs": refc})

    # mappings
    canonical_map_keys = set()
    for e in data:
        cn = _norm(e["crop"]["name_en"]).lower()
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            for it in e.get(kind, []):
                canonical_map_keys.add((cn, code, _norm(it["name_en"]).lower()))
    for cn, code, mn in sorted(canonical_map_keys):
        # only plan create when BOTH the crop and master resolve (else it is
        # implied by their create plans)
        (plan["mappings"]["keep"] if (cn, code, mn) in db_map
         else plan["mappings"]["create"]).append(
            {"crop": cn, "code": code, "master": mn})
    for (cn, code, mn), cpid in existing_map_objs.items():
        if (cn, code, mn) not in canonical_map_keys:
            plan["mappings"]["remove"].append(
                {"crop": cn, "code": code, "master": mn, "mapping_id": cpid})

    return plan


def plan_summary(plan: dict) -> dict:
    def n(section, action):
        return len(plan.get(section, {}).get(action, []))
    return {
        "crops_create": n("crops", "create"),
        "crops_update": n("crops", "update"),
        "crops_keep": n("crops", "keep"),
        "crops_deactivate": n("crops", "deactivate"),
        "pests_create": n("pests", "create"),
        "pests_reuse": n("pests", "reuse"),
        "pests_review": n("pests", "review"),
        "pests_deactivate": n("pests", "deactivate"),
        "diseases_create": n("diseases", "create"),
        "diseases_reuse": n("diseases", "reuse"),
        "diseases_review": n("diseases", "review"),
        "diseases_deactivate": n("diseases", "deactivate"),
        "mappings_create": n("mappings", "create"),
        "mappings_keep": n("mappings", "keep"),
        "mappings_remove": n("mappings", "remove"),
        "history_preserved": len(plan.get("history", {}).get("referenced_legacy", [])),
        "ambiguous": len(plan.get("ambiguous", [])),
    }
