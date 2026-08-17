"""Business location helpers: identity, crop-problem eligibility, hierarchy."""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

from masters.models import CropProblem, ProblemMaster


def models_Q_crop_filter(crop_id):
    """
    Problem is allowed for a crop when:
    - CropProblem maps it to that crop, OR
    - legacy ProblemMaster.crop matches, OR
    - no CropProblem rows exist AND legacy crop is null (global / unrestricted).
    """
    has_any_mapping = Exists(
        CropProblem.objects.filter(problem_master_id=OuterRef("pk"))
    )
    has_this_mapping = Exists(
        CropProblem.objects.filter(
            problem_master_id=OuterRef("pk"),
            crop_id=crop_id,
        )
    )
    return (
        has_this_mapping
        | Q(crop_id=crop_id)
        | (Q(crop_id__isnull=True) & ~has_any_mapping)
    )


def problem_allowed_for_crop(problem: ProblemMaster, crop_id: int | None) -> bool:
    if crop_id in (None, ""):
        return True
    crop_id = int(crop_id)
    if CropProblem.objects.filter(problem_master_id=problem.pk, crop_id=crop_id).exists():
        return True
    if problem.crop_id == crop_id:
        return True
    if problem.crop_id is None and not CropProblem.objects.filter(
        problem_master_id=problem.pk
    ).exists():
        return True
    return False


def normalize_village_name(name: str) -> str:
    return " ".join((name or "").strip().split()).casefold()


def village_identity_key(*, taluk_id: int, official_code: str, name: str) -> str:
    """
    Identity for import dedupe.

    Official PDFs sometimes reuse a village code for distinct E/W (or similar)
    rows, so code alone is not unique. Prefer taluk+code+name when a code
    exists; otherwise taluk+normalized name.
    """
    code = (official_code or "").strip()
    name_cf = normalize_village_name(name)
    if code:
        return f"code:{taluk_id}:{code}:{name_cf}"
    return f"name:{taluk_id}:{name_cf}"
