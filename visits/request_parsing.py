"""Coerce mobile multipart / JSON request values before model validation."""

from __future__ import annotations

from typing import Any, Optional

from rest_framework.exceptions import ValidationError

_TRUTHY = frozenset({"true", "1", "yes", "on", "t"})
_FALSY = frozenset({"false", "0", "no", "off", "f"})


def coerce_optional_bool(value: Any, *, field: str) -> Optional[bool]:
    """
    Accept bool, 0/1, and common string forms from multipart FormData.
    Returns None for empty values. Raises ValidationError for invalid input.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        raise ValidationError({field: f'"{value}" is not a valid boolean.'})
    if isinstance(value, float):
        if value in (0.0, 1.0):
            return bool(int(value))
        raise ValidationError({field: f'"{value}" is not a valid boolean.'})
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    raise ValidationError({field: f'"{text}" value must be either true or false.'})


def apply_coerced_booleans(
    validated_data: dict[str, Any],
    raw: dict,
    *fields: str,
) -> None:
    """Read boolean fields from raw request data into validated_data."""
    for field in fields:
        if field not in raw:
            continue
        validated_data[field] = coerce_optional_bool(raw.get(field), field=field)
