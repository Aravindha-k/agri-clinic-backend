"""API representation helpers — hide legacy Visit.status from clients."""

from __future__ import annotations

HIDDEN_VISIT_API_FIELDS = frozenset({"status"})


def strip_visit_status_from_representation(data: dict) -> dict:
    if isinstance(data, dict):
        data.pop("status", None)
    return data
