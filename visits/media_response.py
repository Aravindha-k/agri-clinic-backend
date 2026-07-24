"""Shared VisitMedia response helpers for mobile + admin serializers."""

from __future__ import annotations

from typing import Any


def build_absolute_media_url(obj, request) -> str | None:
    """Return a production-safe absolute URL, or None if the file is missing."""
    try:
        if not obj or not getattr(obj, "file", None):
            return None
        # Missing storage object should not crash serializers.
        name = getattr(obj.file, "name", None)
        if not name:
            return None
        relative = obj.file.url
    except (ValueError, OSError, FileNotFoundError):
        return None
    if request is not None:
        try:
            return request.build_absolute_uri(relative)
        except Exception:
            return relative
    return relative


def serialize_visit_media(obj, request=None) -> dict[str, Any]:
    """Canonical VisitMedia payload used by mobile and admin."""
    url = build_absolute_media_url(obj, request)
    return {
        "id": obj.pk,
        "media_type": obj.media_type,
        "url": url,
        "file_url": url,  # backward-compatible alias
        "media_url": url,  # docs/legacy alias
        "mime_type": obj.mime_type or "",
        "original_filename": obj.original_filename or "",
        "file_size": obj.file_size,
        "duration_seconds": obj.duration_seconds,
        "caption": obj.caption or "",
        "created_at": (
            (obj.created_at or obj.uploaded_at).isoformat()
            if (obj.created_at or obj.uploaded_at)
            else None
        ),
        "uploaded_at": obj.uploaded_at.isoformat() if obj.uploaded_at else None,
        "client_upload_id": obj.client_upload_id or "",
        "processing_status": obj.processing_status or "ready",
    }


def group_visit_media(media_list: list[dict[str, Any]]) -> dict[str, list]:
    groups = {
        "images": [],
        "audio": [],
        "videos": [],
        "documents": [],
    }
    for row in media_list:
        mt = (row.get("media_type") or "").lower()
        if mt == "image":
            groups["images"].append(row)
        elif mt == "audio":
            groups["audio"].append(row)
        elif mt == "video":
            groups["videos"].append(row)
        else:
            groups["documents"].append(row)
    return groups
