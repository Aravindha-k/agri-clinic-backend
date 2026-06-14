"""Observation / field notes read-write helpers (legacy advice aliases)."""

from __future__ import annotations

from typing import Any

from visits.models import Visit
from visits.request_parsing import apply_coerced_booleans

NOT_ADDED_BY_EMPLOYEE = "Not added by employee"

_LEGACY_ADVICE_FIELDS = (
    ("general_advice", "General"),
    ("fertilizer_advice", "Fertilizer"),
    ("pesticide_advice", "Pesticide"),
    ("irrigation_advice", "Irrigation"),
)

_BOOLEAN_WRITE_FIELDS = ("follow_up_required", "pest_issue", "disease_issue")


def _text(value) -> str:
    return (value or "").strip()


def legacy_advice_text(visit: Visit) -> str:
    parts = []
    for attr, label in _LEGACY_ADVICE_FIELDS:
        chunk = _text(getattr(visit, attr, None))
        if chunk:
            parts.append(f"{label}: {chunk}" if len(_LEGACY_ADVICE_FIELDS) > 1 else chunk)
    return "\n".join(parts).strip()


def stored_recommendation(visit: Visit) -> str:
    return _text(getattr(visit, "recommendation", None))


def stored_field_notes(visit: Visit) -> str:
    return _text(getattr(visit, "field_notes", None))


def stored_observation(visit: Visit) -> str:
    return _text(getattr(visit, "observation", None))


def resolved_field_notes(visit: Visit) -> str:
    stored = stored_field_notes(visit)
    if stored:
        return stored
    stored_obs = stored_observation(visit)
    if stored_obs:
        return stored_obs
    return legacy_advice_text(visit) or _text(visit.notes)


def resolved_recommendation(visit: Visit) -> str:
    stored = stored_recommendation(visit)
    if stored:
        return stored
    # Legacy rows: recommendation was aliased to field_notes before dedicated column.
    if not stored_observation(visit):
        legacy = stored_field_notes(visit) or legacy_advice_text(visit)
        if legacy:
            return legacy
    return ""


def display_text(value: str) -> str:
    return value if value else NOT_ADDED_BY_EMPLOYEE


def display_field_notes(visit: Visit) -> str:
    return display_text(resolved_field_notes(visit))


def display_recommendation(visit: Visit) -> str:
    return display_text(resolved_recommendation(visit))


def display_observation(visit: Visit) -> str:
    stored = stored_observation(visit)
    if stored:
        return display_text(stored)
    legacy = resolved_field_notes(visit)
    return display_text(legacy)


def display_problem_seen(visit: Visit) -> str:
    return display_text(_text(getattr(visit, "problem_seen", None)))


def display_action_taken(visit: Visit) -> str:
    return display_text(_text(getattr(visit, "action_taken", None)))


def follow_up_date_value(visit: Visit):
    return visit.next_visit_date


def build_crop_object(visit: Visit) -> dict[str, Any] | None:
    if not visit.crop_id:
        return None
    crop = visit.crop
    return {
        "id": crop.id,
        "name_en": crop.name_en,
        "name_ta": crop.name_ta,
        "name": crop.name_en if not crop.name_ta else f"{crop.name_en} / {crop.name_ta}",
    }


def observation_response_block(visit: Visit) -> dict[str, Any]:
    """Standard observation / field notes block for list and detail APIs."""
    return {
        "crop": visit.crop_id,
        "crop_id": visit.crop_id,
        "crop_name": _crop_name_label(visit),
        "crop_info": build_crop_object(visit),
        "observation": display_observation(visit),
        "field_notes": display_field_notes(visit),
        "problem_seen": display_problem_seen(visit),
        "action_taken": display_action_taken(visit),
        "follow_up_date": follow_up_date_value(visit),
        "follow_up_required": visit.follow_up_required,
        "recommendation": display_recommendation(visit),
        "general_advice": visit.general_advice or "",
        "fertilizer_advice": visit.fertilizer_advice or "",
        "pesticide_advice": visit.pesticide_advice or "",
        "irrigation_advice": visit.irrigation_advice or "",
        "notes": visit.notes or "",
    }


def _crop_name_label(visit: Visit) -> str:
    from visits.visit_response import crop_display_name

    return crop_display_name(visit)


def _legacy_field_notes_from_advice(raw: dict) -> str:
    parts = [
        _text(raw.get(key))
        for key in (
            "general_advice",
            "fertilizer_advice",
            "pesticide_advice",
            "irrigation_advice",
        )
        if _text(raw.get(key))
    ]
    return "\n".join(parts).strip()


def apply_observation_write(
    validated_data: dict[str, Any],
    raw: dict | None,
    *,
    instance: Visit | None = None,
) -> dict[str, Any]:
    """Map mobile/admin payload into Visit columns (create/update)."""
    raw = raw if isinstance(raw, dict) else {}

    recommendation = _text(raw.get("recommendation")) or _text(raw.get("advice"))
    observation = _text(raw.get("observation"))
    field_notes = _text(raw.get("field_notes")) or _text(raw.get("notes"))
    problem_seen = _text(raw.get("problem_seen"))
    action_taken = _text(raw.get("action_taken"))

    if not field_notes:
        field_notes = _legacy_field_notes_from_advice(raw)

    write_keys = (
        "field_notes",
        "observation",
        "notes",
        "recommendation",
        "advice",
        "general_advice",
        "fertilizer_advice",
        "pesticide_advice",
        "irrigation_advice",
    )

    if recommendation or "recommendation" in raw or "advice" in raw:
        validated_data["recommendation"] = recommendation or None

    if "observation" in raw:
        validated_data["observation"] = observation or None
    elif observation:
        validated_data["observation"] = observation
    elif recommendation and ("recommendation" in raw or "advice" in raw):
        # Legacy clients: recommendation-only submit without a separate observation key.
        validated_data["observation"] = recommendation
    elif field_notes or any(k in raw for k in write_keys):
        validated_data["observation"] = field_notes or None

    if field_notes or "field_notes" in raw or "notes" in raw:
        validated_data["field_notes"] = field_notes or None

    if problem_seen or "problem_seen" in raw:
        validated_data["problem_seen"] = problem_seen or None
    if action_taken or "action_taken" in raw:
        validated_data["action_taken"] = action_taken or None

    if _text(raw.get("general_advice")) or "general_advice" in raw:
        validated_data["general_advice"] = _text(raw.get("general_advice")) or None

    follow_up = raw.get("follow_up_date")
    if follow_up not in (None, ""):
        validated_data["next_visit_date"] = follow_up

    apply_coerced_booleans(validated_data, raw, *_BOOLEAN_WRITE_FIELDS)

    if field_notes and not _text(validated_data.get("notes")):
        validated_data.setdefault("notes", field_notes)

    for key in (
        "fertilizer_advice",
        "pesticide_advice",
        "irrigation_advice",
    ):
        if key in raw:
            validated_data[key] = _text(raw.get(key)) or None

    return validated_data
