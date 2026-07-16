"""Canonical visit submit/replay response mapping."""

from __future__ import annotations

from typing import Any

from visits.models import Visit


def build_visit_submit_response(
    visit: Visit,
    *,
    created: bool,
    duplicate: bool,
    route_point_id: int | None = None,
    media_count: int | None = None,
    errors: Any = None,
) -> dict[str, Any]:
    """Stable create/replay contract used by all submit paths."""
    if media_count is None:
        media_count = visit.media_files.count() if visit.pk else 0

    visited_at = None
    if visit.visit_date and visit.visit_time:
        visited_at = f"{visit.visit_date.isoformat()}T{visit.visit_time.isoformat()}"
    elif visit.visit_date:
        visited_at = visit.visit_date.isoformat()

    return {
        "visit_id": visit.pk,
        "local_sync_id": visit.local_sync_id,
        "created": bool(created),
        "duplicate": bool(duplicate),
        "status": visit.status or "completed",
        "farmer_id": visit.farmer_id,
        "duty_session_id": visit.duty_session_id,
        "visited_at": visited_at,
        "visit_date": str(visit.visit_date) if visit.visit_date else None,
        "latitude": visit.latitude,
        "longitude": visit.longitude,
        "route_point_id": route_point_id,
        "media_count": media_count,
        "errors": errors,
    }


def build_bulk_item_response(
    *,
    local_sync_id: str | None,
    visit: Visit | None,
    created: bool,
    duplicate: bool,
    status_label: str,
    errors: Any = None,
) -> dict[str, Any]:
    return {
        "local_sync_id": local_sync_id,
        "visit_id": visit.pk if visit is not None else None,
        "created": created,
        "duplicate": duplicate,
        "status": status_label,
        "errors": errors,
        "duty_session_id": visit.duty_session_id if visit is not None else None,
        "farmer_id": visit.farmer_id if visit is not None else None,
    }
