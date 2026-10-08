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
# Identity helpers -- PHASE 2B: exact PDF text, whitespace-trimmed only.
#
# Canonical ProblemMaster identity is (category + EXACT APPROVED PDF ENGLISH
# VALUE).  Case variants ("Fruit Borer" vs "Fruit borer"), spacing variants
# ("Mealy Bug" vs "Mealybug") and spelling variants ("Bettle" vs "Beetle") are
# DISTINCT canonical masters until manual business normalization is approved.
# Pest and Disease are always different categories even for identical text.
# ---------------------------------------------------------------------------

def _exact(s) -> str:
    """Exact-identity key: collapse repeated whitespace, trim, keep case."""
    return re.sub(r"\s+", " ", (s or "").strip())


def _db_models():
    from masters.models import Crop, ProblemCategory, ProblemMaster, CropProblem
    return Crop, ProblemCategory, ProblemMaster, CropProblem


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


# Source-data anomalies flagged for business review.  The PDF value is kept
# verbatim in the canonical JSON; this list only marks it for review -- it is
# never corrected by code.
TAMIL_ANOMALIES = [
    {
        "crop": "Greens",
        "kind": "pests",
        "name_en": "Mites",
        "name_ta": "முட்டை பூச்சி",
        "flag": "SOURCE_DATA_REVIEW",
        "reason": "visually-verified PDF value preserved verbatim; reads like a "
                  "source typo (expected a mite term), pending business review",
    },
]


def canonical_master_keys(data) -> dict:
    """Map (category, EXACT canonical English name) -> set of crop names.

    Exact identity: whitespace-trimmed, case preserved.  Case/spacing/spelling
    variants produce DISTINCT keys (no merging).
    """
    keys = {}
    for e in data:
        cn = _exact(e["crop"]["name_en"])
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            for it in e.get(kind, []):
                key = (code, _exact(it["name_en"]))
                keys.setdefault(key, set()).add(cn)
    return keys


def canonical_map_keys(data) -> set:
    """Set of canonical (crop, category, exact master name) associations.

    A set -- so the in-crop exact duplicate in the source (Groundnut 'Stem rot')
    collapses to ONE planned CropProblem mapping.
    """
    out = set()
    for e in data:
        cn = _exact(e["crop"]["name_en"])
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            for it in e.get(kind, []):
                out.add((cn, code, _exact(it["name_en"])))
    return out


def source_duplicates(data) -> list:
    """In-crop exact duplicates present in the PDF source (report only)."""
    dups = []
    for e in data:
        cn = _exact(e["crop"]["name_en"])
        for kind, code in (("pests", PEST), ("diseases", DISEASE)):
            seen = set()
            for it in e.get(kind, []):
                nm = _exact(it["name_en"])
                if nm in seen:
                    dups.append({"crop": cn, "category": code, "name": nm})
                seen.add(nm)
    return dups


def tamil_anomalies(data) -> list:
    """Return the TAMIL_ANOMALIES entries that are present in the dataset."""
    out = []
    for flag in TAMIL_ANOMALIES:
        for e in data:
            if _exact(e["crop"]["name_en"]) != flag["crop"]:
                continue
            for it in e.get(flag["kind"], []):
                if _exact(it["name_en"]) == flag["name_en"]:
                    out.append({**flag, "canon_ta": it.get("name_ta")})
    return out


def compare_to_db(data=None) -> dict:
    """READ-ONLY comparison of canonical data against current DB rows.

    PHASE 2B identity: EXACT PDF English value (whitespace-trimmed, case kept).
    Returns a classification dict; performs zero writes.
    """
    Crop, ProblemCategory, ProblemMaster, CropProblem = _db_models()
    if data is None:
        data = load_canonical()

    db_crops = list(Crop.objects.all())
    db_crops_exact = {}
    db_crops_casefold = {}
    for c in db_crops:
        db_crops_exact.setdefault(_exact(c.name_en), []).append(c)
        db_crops_casefold.setdefault(_exact(c.name_en).lower(), []).append(c)

    # --- crops ---
    crop_cmp = {"canonical_exact": [], "update_required": [],
                "canonical_missing": [], "ambiguous": []}
    canonical_crop_keys = set()
    for entry in data:
        en = _exact(entry["crop"]["name_en"])
        ta = _exact(entry["crop"]["name_ta"])
        canonical_crop_keys.add(en)
        hits = db_crops_exact.get(en, [])
        if len(hits) == 1:
            db = hits[0]
            if _exact(db.name_ta) != ta or not db.is_active:
                crop_cmp["update_required"].append(
                    {"crop": en, "db_id": db.id, "db_ta": db.name_ta,
                     "canon_ta": ta, "reactivate": not db.is_active})
            else:
                crop_cmp["canonical_exact"].append({"crop": en, "db_id": db.id})
        elif len(hits) > 1:
            crop_cmp["ambiguous"].append(
                {"crop": en, "candidates": [h.id for h in hits]})
        else:
            # case-only near-match -> ambiguous (requires decision, not reuse)
            casefold_hits = [c for c in db_crops_casefold.get(en.lower(), [])
                             if _exact(c.name_en) != en]
            if casefold_hits:
                crop_cmp["ambiguous"].append(
                    {"crop": en, "reason": "case-only near-match",
                     "candidates": [{"db_id": c.id, "name": c.name_en}
                                    for c in casefold_hits]})
            else:
                crop_cmp["canonical_missing"].append(
                    {"crop": en, "canon_ta": ta})
    legacy_db_only = [c for c in db_crops
                      if _exact(c.name_en) not in canonical_crop_keys]
    crop_cmp["legacy_only"] = [{"crop": c.name_en, "db_id": c.id,
                                "is_active": c.is_active}
                               for c in legacy_db_only]

    # --- problem masters ---
    cat_by_code = {pc.code: pc for pc in ProblemCategory.objects.all()}
    pest_cat = cat_by_code.get(PEST)
    disease_cat = cat_by_code.get(DISEASE)
    db_masters = list(ProblemMaster.objects.select_related("category", "crop"))
    masters_exact = {}
    for m in db_masters:
        code = m.category.code if m.category_id else None
        masters_exact.setdefault((code, _exact(m.name)), []).append(m)

    ckeys = canonical_master_keys(data)
    master_cmp = {"exact_reusable": [], "variant_requires_approval": [],
                  "canonical_missing": [], "ambiguous": []}
    for (code, mn) in sorted(ckeys):
        hits = masters_exact.get((code, mn), [])
        if len(hits) == 1:
            m = hits[0]
            canon_ta = _find_ta(data, code, m.name)
            entry = {"master": mn, "db_id": m.id}
            if _exact(m.tamil_name) and canon_ta and \
               _exact(m.tamil_name) != _exact(canon_ta):
                entry["tamil_differs"] = m.tamil_name
            master_cmp["exact_reusable"].append(entry)
        elif len(hits) > 1:
            master_cmp["ambiguous"].append(
                {"master": mn, "code": code,
                 "candidates": [h.id for h in hits]})
        else:
            cand = _find_master_variant(db_masters, code, mn)
            if cand:
                master_cmp["variant_requires_approval"].append(
                    {"master": mn, "code": code,
                     "candidates": [{"db_id": c.id, "name": c.name}
                                    for c in cand]})
            else:
                master_cmp["canonical_missing"].append(
                    {"master": mn, "code": code})
    legacy_masters = [m for m in db_masters
                      if (m.category.code if m.category_id else None)
                      in CROP_HEALTH_CODES
                      and (m.category.code, _exact(m.name)) not in ckeys]
    non_crop_health = [m for m in db_masters
                       if (m.category.code if m.category_id else None)
                       not in CROP_HEALTH_CODES]
    master_cmp["legacy_only"] = [
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
        db_map_keys.add((_exact(cp.crop.name_en),
                         cp.problem_master.category.code if cp.problem_master.category_id else None,
                         _exact(cp.problem_master.name)))
    canon_map = canonical_map_keys(data)
    mapping_cmp = {"exists": [], "missing": [], "legacy_noncanonical": [],
                   "ambiguous": []}
    for k in sorted(canon_map):
        (mapping_cmp["exists"] if k in db_map_keys
         else mapping_cmp["missing"]).append(
            {"crop": k[0], "code": k[1], "master": k[2]})
    for k in db_map_keys:
        if k not in canon_map:
            mapping_cmp["legacy_noncanonical"].append(
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
                if _exact(it["name_en"]) == _exact(name):
                    return it.get("name_ta") or ""
    return ""


def _find_master_variant(db_masters, code, exact_name):
    """Near-name candidates in the same category (case/spacing/spelling).

    Used ONLY to surface VARIANT_REQUIRES_APPROVAL candidates -- never to
    merge or reuse.
    """
    import difflib
    out = []
    target = _exact(exact_name)
    for m in db_masters:
        mcode = m.category.code if m.category_id else None
        if mcode != code:
            continue
        mn = _exact(m.name)
        if mn == target:
            continue
        if _squash(mn) == _squash(target) or \
           difflib.SequenceMatcher(None, mn.lower(), target.lower()).ratio() > 0.8:
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

def db_counts() -> dict:
    """Actual row counts for the production-preflight report.  READ-ONLY."""
    Crop, ProblemCategory, ProblemMaster, CropProblem = _db_models()
    from visits.models import Visit
    return {
        "crop_total": Crop.objects.count(),
        "crop_active": Crop.objects.filter(is_active=True).count(),
        "problem_category_total": ProblemCategory.objects.count(),
        "problem_master_total": ProblemMaster.objects.count(),
        "problem_master_active": ProblemMaster.objects.filter(is_active=True).count(),
        "crop_problem_total": CropProblem.objects.count(),
        "visit_total": Visit.objects.count(),
    }


def build_dry_run_plan(data=None) -> dict:
    """Compute the migration plan WITHOUT writing anything.

    PHASE 2B rules:
    * Crop in canonical PDF -> active; not in PDF -> inactive (never delete).
    * ProblemMaster used by >=1 canonical crop (exact identity) -> active;
      else -> inactive.  A shared master is NOT deactivated just because one
      crop mapping goes away.
    * Canonical (crop, category, master) mapping -> ensure exists; noncanonical
      -> remove mapping.
    * Historical Visits are never touched.
    * disease category exists-but-inactive -> PLANNED reactivation only
      (reported; never performed here).

    This function performs zero ORM writes -- SELECTs only.
    """
    Crop, ProblemCategory, ProblemMaster, CropProblem = _db_models()
    if data is None:
        data = load_canonical()
    refs = historical_reference_counts()
    variants = analyze_variants(data)

    db_crops_exact = {}
    for c in Crop.objects.all():
        db_crops_exact.setdefault(_exact(c.name_en), []).append(c)
    db_masters = {}
    for m in ProblemMaster.objects.select_related("category"):
        code = m.category.code if m.category_id else None
        db_masters.setdefault((code, _exact(m.name)), []).append(m)
    existing_map_objs = {}
    for cp in CropProblem.objects.select_related("crop", "problem_master__category"):
        existing_map_objs[(_exact(cp.crop.name_en),
                           cp.problem_master.category.code if cp.problem_master.category_id else None,
                           _exact(cp.problem_master.name))] = cp.id
    db_map = set(existing_map_objs.keys())

    ckeys = canonical_master_keys(data)          # {(code, exact_name): {crops}}
    cmap = canonical_map_keys(data)              # {(crop, code, exact_name)}

    plan = {
        "crops": {"create": [], "reuse": [], "update": [], "deactivate": []},
        "pests": {"create": [], "reuse": [], "review": [], "deactivate": []},
        "diseases": {"create": [], "reuse": [], "review": [], "deactivate": []},
        "categories": {},
        "mappings": {"create": [], "keep": [], "remove": []},
        "history": {"referenced_legacy": []},
        "review_items": {},
        "ambiguous": [],
    }

    # --- categories (planned only -- never performed) ---
    for code in CROP_HEALTH_CODES:
        cat = ProblemCategory.objects.filter(code=code).first()
        if cat is None:
            plan["categories"][code] = {"action": "create"}
        elif not cat.is_active:
            plan["categories"][code] = {
                "action": "activate", "db_id": cat.id, "name": cat.name,
                "note": "reuse existing record; set is_active=True at import"}
        else:
            plan["categories"][code] = {
                "action": "keep", "db_id": cat.id, "name": cat.name}

    # --- crops ---
    canonical_crop_keys = set()
    for e in data:
        en = _exact(e["crop"]["name_en"])
        ta = _exact(e["crop"]["name_ta"])
        canonical_crop_keys.add(en)
        hits = db_crops_exact.get(en, [])
        if not hits:
            plan["crops"]["create"].append({"crop": en, "name_ta": ta})
        elif len(hits) == 1:
            db = hits[0]
            needs_update = _exact(db.name_ta) != ta
            if needs_update or not db.is_active:
                plan["crops"]["update"].append(
                    {"crop": en, "db_id": db.id,
                     "from_ta": db.name_ta if needs_update else None,
                     "to_ta": ta if needs_update else None,
                     "reactivate": not db.is_active})
            else:
                plan["crops"]["reuse"].append({"crop": en, "db_id": db.id})
        else:
            plan["ambiguous"].append(
                {"type": "crop", "name": en,
                 "candidates": [h.id for h in hits]})
    for c in Crop.objects.all():
        if _exact(c.name_en) not in canonical_crop_keys:
            refc = refs["crop_refs"].get(c.id, 0)
            plan["crops"]["deactivate"].append(
                {"crop": c.name_en, "db_id": c.id, "is_active": c.is_active,
                 "visit_refs": refc,
                 "preserve": "kept inactive; never hard-deleted"})
            if refc:
                plan["history"]["referenced_legacy"].append(
                    {"type": "crop", "name": c.name_en, "db_id": c.id,
                     "visit_refs": refc})

    # --- masters (exact identity; variant hits -> review only) ---
    all_db_masters = list(ProblemMaster.objects.select_related("category"))
    for code, mn in sorted(ckeys):
        slot = "pests" if code == PEST else "diseases"
        hits = db_masters.get((code, mn), [])
        if len(hits) == 1:
            entry = {"master": mn, "db_id": hits[0].id}
            if not hits[0].is_active:
                entry["reactivate"] = True
            plan[slot]["reuse"].append(entry)
        elif len(hits) > 1:
            plan[slot]["review"].append(
                {"master": mn, "code": code,
                 "candidates": [h.id for h in hits],
                 "reason": "multiple db rows share exact name"})
            plan["ambiguous"].append(
                {"type": "master", "name": mn, "code": code,
                 "candidates": [h.id for h in hits]})
        else:
            cand = _find_master_variant(all_db_masters, code, mn)
            if cand:
                plan[slot]["review"].append(
                    {"master": mn, "code": code,
                     "candidates": [{"db_id": c.id, "name": c.name}
                                    for c in cand],
                     "reason": "VARIANT_REQUIRES_APPROVAL -- near-name db row "
                               "is NOT exact; do not reuse without approval"})
            else:
                plan[slot]["create"].append({"master": mn, "code": code})

    # --- legacy masters (pest/disease category, not canonical) -> deactivate
    for m in all_db_masters:
        code = m.category.code if m.category_id else None
        if code not in CROP_HEALTH_CODES:
            continue
        if (code, _exact(m.name)) in ckeys:
            continue
        refc = refs["master_refs"].get(m.id, 0)
        plan["pests" if code == PEST else "diseases"]["deactivate"].append(
            {"master": m.name, "db_id": m.id, "code": code,
             "is_active": m.is_active, "visit_refs": refc})
        if refc:
            plan["history"]["referenced_legacy"].append(
                {"type": "master", "name": m.name, "db_id": m.id,
                 "visit_refs": refc})

    # --- mappings ---
    for cn, code, mn in sorted(cmap):
        (plan["mappings"]["keep"] if (cn, code, mn) in db_map
         else plan["mappings"]["create"]).append(
            {"crop": cn, "code": code, "master": mn})
    for (cn, code, mn), cpid in existing_map_objs.items():
        if (cn, code, mn) not in cmap:
            plan["mappings"]["remove"].append(
                {"crop": cn, "code": code, "master": mn, "mapping_id": cpid})

    # --- review items (report only) ---
    dups = source_duplicates(data)
    plan["review_items"] = {
        "source_duplicates": {
            "count": len(dups),
            "items": dups,
            "planned_db_mappings": 0,
            "note": "PDF lists the same value twice in one crop; CropProblem "
                    "uniqueness means exactly ONE mapping is planned."},
        "case_variants": {
            "pest": [g["variants"] for g in variants[PEST]["case_only_variants"]],
            "disease": [g["variants"] for g in variants[DISEASE]["case_only_variants"]],
            "preserved_separately": True},
        "spacing_variants": {
            "pest": variants[PEST]["spacing_variants"],
            "disease": variants[DISEASE]["spacing_variants"],
            "preserved_separately": True},
        "spelling_variants": {
            "pest": variants[PEST]["spelling_variants"],
            "disease": variants[DISEASE]["spelling_variants"],
            "preserved_separately": True},
        "tamil_source_anomalies": tamil_anomalies(data),
    }

    return plan


def plan_summary(plan: dict) -> dict:
    def n(section, action):
        return len(plan.get(section, {}).get(action, []))
    return {
        "crops_create": n("crops", "create"),
        "crops_reuse": n("crops", "reuse"),
        "crops_update": n("crops", "update"),
        "crops_deactivate": n("crops", "deactivate"),
        "pest_category_action": plan.get("categories", {}).get(PEST, {}).get("action"),
        "disease_category_action": plan.get("categories", {}).get(DISEASE, {}).get("action"),
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
        "review_items": {
            "source_duplicates": plan.get("review_items", {})
                                     .get("source_duplicates", {}).get("count", 0),
            "tamil_source_anomalies": len(plan.get("review_items", {})
                                             .get("tamil_source_anomalies", [])),
        },
        "ambiguous": len(plan.get("ambiguous", [])),
    }
