"""Safe parsing for common dashboard/list query parameters."""

from __future__ import annotations


def parse_bounded_int(
    raw: str | None,
    *,
    default: int,
    minimum: int = 1,
    maximum: int = 365,
) -> int:
    """
    Parse an integer query param with bounds. Non-numeric values fall back to default.
    """
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))
