"""Observation / field notes read-write helpers (legacy advice aliases)."""

from __future__ import annotations

from typing import Any

from visits.models import Visit

NOT_ADDED_BY_EMPLOYEE = "Not added by employee"

_LEGACY_ADVICE_FIELDS = (
    ("general_advice", "General"),
    ("fertilizer_advice", "Fertilizer"),
    ("pesticide_advice", "Pesticide"),
    ("irrigation_advice", "Irrigation"),
)


def _text(value) -> str:
    return (value or "").strip()


def legacy_advice_text(visit: Visit) -> str:
    parts = []
    for attr, label in _LEGACY_ADVICE_FIELDS:
        chunk = _text(getattr(visit, attr, None))
        if chunk:
            parts.append(f"{label}: {chunk}" if len(_LEGACY_ADVICE_FIELDS) > 1 else chunk)
    return "\n".join(parts).strip()


def stored_field_notes(visit: Visit) -> str:
    return (
        _text(getattr(visit, "field_notes", None))
        or _text(getattr(visit, "observation", None))
        or _text(visit.notes)
    )


def resolved_field_notes(visit: Visit) -> str:
    stored = stored_field_notes(visit)
    if stored:
        return stored
    return legacy_advice_text(visit)


def display_text(value: str) -> str:
    return value if value else NOT_ADDED_BY_EMPLOYEE


def display_field_notes(visit: Visit) -> str:
    return display_text(resolved_field_notes(visit))


def display_observation(visit: Visit) -> str:
    return display_text(_text(getattr(visit, "observation", None)) or resolved_field_notes(visit))


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
        # Backward-compatible aliases (read-only in responses)
        "recommendation": display_field_notes(visit),
        "general_advice": visit.general_advice or "",
        "fertilizer_advice": visit.fertilizer_advice or "",
        "pesticide_advice": visit.pesticide_advice or "",
        "irrigation_advice": visit.irrigation_advice or "",
        "notes": visit.notes or "",
    }


def _crop_name_label(visit: Visit) -> str:
    from visits.visit_response import crop_display_name

    return crop_display_name(visit)


def apply_observation_write(
    validated_data: dict[str, Any],
    raw: dict | None,
    *,
    instance: Visit | None = None,
) -> dict[str, Any]:
    """Map mobile/admin payload into Visit columns (create/update)."""
    raw = raw if isinstance(raw, dict) else {}

    field_notes = (
        _text(raw.get("field_notes"))
        or _text(raw.get("observation"))
        or _text(raw.get("notes"))
        or _text(raw.get("recommendation"))
        or _text(raw.get("advice"))
        or _text(raw.get("general_advice"))
    )
    if not field_notes:
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
        field_notes = "\n".join(parts) if parts else ""

    observation = _text(raw.get("observation")) or field_notes
    problem_seen = _text(raw.get("problem_seen"))
    action_taken = _text(raw.get("action_taken"))

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
    if field_notes or any(k in raw for k in write_keys):
        validated_data["field_notes"] = field_notes or None
    if observation or "observation" in raw or any(k in raw for k in write_keys):
        validated_data["observation"] = observation or None
    if problem_seen or "problem_seen" in raw:
        validated_data["problem_seen"] = problem_seen or None
    if action_taken or "action_taken" in raw:
        validated_data["action_taken"] = action_taken or None

    if field_notes and not _text(raw.get("general_advice")):
        validated_data.setdefault("general_advice", field_notes)
    if field_notes and not _text(validated_data.get("notes")):
        validated_data.setdefault("notes", field_notes)

    follow_up = raw.get("follow_up_date")
    if follow_up not in (None, ""):
        validated_data["next_visit_date"] = follow_up
    if "follow_up_required" in raw:
        validated_data["follow_up_required"] = raw.get("follow_up_required")

    for key in (
        "fertilizer_advice",
        "pesticide_advice",
        "irrigation_advice",
        "general_advice",
    ):
        if key in raw:
            validated_data[key] = _text(raw.get(key)) or None

    return validated_data
