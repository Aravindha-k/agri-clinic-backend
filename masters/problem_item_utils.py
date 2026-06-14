"""Problem Item API helpers (ProblemMaster + ProblemCategory)."""

from __future__ import annotations

from masters.models import ProblemCategory

# API category codes (web/mobile Problem Items screen).
API_CATEGORY_PEST = "pest"
API_CATEGORY_DISEASE = "disease"
API_CATEGORY_NUTRIENT = "nutrient_issue"

ALLOWED_API_CATEGORIES = frozenset(
    {API_CATEGORY_PEST, API_CATEGORY_DISEASE, API_CATEGORY_NUTRIENT}
)

_API_TO_DB_CATEGORY = {
    API_CATEGORY_PEST: ProblemCategory.CODE_PEST,
    API_CATEGORY_DISEASE: ProblemCategory.CODE_DISEASE,
    API_CATEGORY_NUTRIENT: ProblemCategory.CODE_NUTRIENT,
}

_DB_TO_API_CATEGORY = {v: k for k, v in _API_TO_DB_CATEGORY.items()}


def api_category_code(db_code: str | None) -> str | None:
    if not db_code:
        return None
    return _DB_TO_API_CATEGORY.get(db_code.strip(), db_code.strip())


def db_category_code(api_code: str) -> str:
    key = (api_code or "").strip().lower()
    if key not in _API_TO_DB_CATEGORY:
        raise ValueError(f"Invalid category: {api_code}")
    return _API_TO_DB_CATEGORY[key]


def get_category_for_api_code(api_code: str) -> ProblemCategory:
    code = db_category_code(api_code)
    try:
        return ProblemCategory.objects.get(code=code, is_active=True)
    except ProblemCategory.DoesNotExist as exc:
        raise ValueError(f"Problem category '{code}' is not configured.") from exc


def problem_categories_with_active_items():
    """Active categories referenced by at least one active problem item."""
    from masters.models import ProblemMaster

    used_ids = (
        ProblemMaster.objects.filter(is_active=True)
        .values_list("category_id", flat=True)
        .distinct()
    )
    return ProblemCategory.objects.filter(id__in=used_ids, is_active=True).order_by(
        "name"
    )
