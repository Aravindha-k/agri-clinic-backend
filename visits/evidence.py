"""Unified visit-evidence READ contract (VisitAttachment + VisitMedia).

Write/delete contracts stay model-specific. This module only normalizes
list/read payloads so Admin can display mobile-uploaded VisitMedia.
"""

from __future__ import annotations

import os
from typing import Any

from visits.attachment_serializers import VisitAttachmentSerializer
from visits.media_response import build_absolute_media_url
from visits.models import VisitAttachment, VisitMedia

SOURCE_VISIT_ATTACHMENT = "visit_attachment"
SOURCE_VISIT_MEDIA = "visit_media"


def evidence_key(source: str, source_id: int) -> str:
    return f"{source}:{source_id}"


def normalize_evidence_attachment_type(
    *,
    media_type: str = "",
    attachment_type: str = "",
    mime_type: str = "",
    filename: str = "",
) -> str:
    """Map both models onto one display type without treating all MIME as evidence."""
    raw = (attachment_type or media_type or "").strip().lower()
    mime = (mime_type or "").strip().lower()
    name = (filename or "").strip().lower()

    if raw in {"image", "pdf", "audio", "text", "video", "other"}:
        return raw
    if raw == "bill":
        if mime == "application/pdf" or name.endswith(".pdf"):
            return "pdf"
        if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return "image"
        return "other"

    if mime.startswith("image/"):
        return "image"
    if mime == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if raw:
        return "other"
    return "other"


def _storage_name(obj) -> str:
    try:
        name = getattr(getattr(obj, "file", None), "name", "") or ""
    except (ValueError, OSError):
        return ""
    return str(name).replace("\\", "/").lstrip("/")


def _filename(obj, original: str = "") -> str:
    if original:
        return original
    stored = _storage_name(obj)
    return os.path.basename(stored) if stored else ""


def _public_file_url(obj, request) -> str | None:
    return build_absolute_media_url(obj, request)


def serialize_attachment_evidence(obj: VisitAttachment, request) -> dict[str, Any]:
    data = VisitAttachmentSerializer(obj, context={"request": request}).data
    file_url = data.get("file_url") or _public_file_url(obj, request)
    filename = _filename(obj, obj.original_filename or "")
    created = obj.uploaded_at.isoformat() if obj.uploaded_at else None
    source_id = obj.pk
    data.update(
        {
            "id": source_id,
            "source": SOURCE_VISIT_ATTACHMENT,
            "source_id": source_id,
            "evidence_key": evidence_key(SOURCE_VISIT_ATTACHMENT, source_id),
            "attachment_type": normalize_evidence_attachment_type(
                attachment_type=obj.attachment_type,
                mime_type=obj.mime_type or "",
                filename=filename,
            ),
            "file_url": file_url,
            "url": file_url,
            "filename": filename,
            "created_at": created,
        }
    )
    return data


def serialize_media_evidence(obj: VisitMedia, request) -> dict[str, Any]:
    file_url = _public_file_url(obj, request)
    filename = _filename(obj, obj.original_filename or "")
    created_dt = obj.created_at or obj.uploaded_at
    created = created_dt.isoformat() if created_dt else None
    uploaded = obj.uploaded_at.isoformat() if obj.uploaded_at else None
    source_id = obj.pk
    attachment_type = normalize_evidence_attachment_type(
        media_type=obj.media_type,
        mime_type=obj.mime_type or "",
        filename=filename,
    )
    # VisitMedia ids are not VisitAttachment ids. Expose a non-numeric list id
    # so clients cannot DELETE /attachments/<pk> against the wrong table.
    return {
        "id": evidence_key(SOURCE_VISIT_MEDIA, source_id),
        "source": SOURCE_VISIT_MEDIA,
        "source_id": source_id,
        "evidence_key": evidence_key(SOURCE_VISIT_MEDIA, source_id),
        "attachment_type": attachment_type,
        "media_type": obj.media_type,
        "file_url": file_url,
        "url": file_url,
        "media_url": file_url,
        "mime_type": obj.mime_type or "",
        "filename": filename,
        "original_filename": obj.original_filename or "",
        "file_size": obj.file_size,
        "created_at": created,
        "uploaded_at": uploaded,
        "uploaded_by": obj.uploaded_by_id,
        "client_upload_id": obj.client_upload_id or "",
        "processing_status": obj.processing_status or "ready",
        "caption": obj.caption or "",
        "text_content": None,
    }


def _sort_key(row: dict[str, Any]) -> tuple:
    stamp = row.get("created_at") or row.get("uploaded_at") or ""
    return (stamp, row.get("evidence_key") or "")


def _dedupe_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact storage-path duplicates only (dual-write of the same file)."""
    seen_paths: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        path = (row.pop("_storage_name", None) or "").strip()
        if path:
            if path in seen_paths:
                continue
            seen_paths.add(path)
        out.append(row)
    return out


def list_visit_evidence(visit, request) -> list[dict[str, Any]]:
    """Normalized evidence for one visit: attachments + media, oldest first."""
    rows: list[dict[str, Any]] = []

    # Prefer prefetched reverse relations to avoid N+1 on list endpoints.
    pref = getattr(visit, "_prefetched_objects_cache", {}) or {}
    if "attachments" in pref:
        attachments = list(visit.attachments.all())
    else:
        attachments = list(
            VisitAttachment.objects.filter(visit=visit)
            .select_related("employee", "uploaded_by", "visit")
            .order_by("uploaded_at", "id")
        )
    for obj in attachments:
        row = serialize_attachment_evidence(obj, request)
        row["_storage_name"] = _storage_name(obj)
        rows.append(row)

    if "media_files" in pref:
        media = list(visit.media_files.all())
    else:
        media = list(
            VisitMedia.objects.filter(visit=visit)
            .select_related("uploaded_by")
            .order_by("uploaded_at", "id")
        )
    for obj in media:
        row = serialize_media_evidence(obj, request)
        row["_storage_name"] = _storage_name(obj)
        rows.append(row)

    rows = _dedupe_evidence(rows)
    rows.sort(key=_sort_key)
    return rows


def build_visit_evidence_preview(
    visit,
    request,
    *,
    limit: int = 3,
    images_only: bool = True,
) -> dict[str, Any]:
    """
    Lightweight list-preview for farmer visit history cards.

    Returns total evidence_count (all types) and a small image preview list.
    """
    rows = list_visit_evidence(visit, request)
    preview_source = rows
    if images_only:
        preview_source = [
            r
            for r in rows
            if (r.get("attachment_type") == "image")
            or str(r.get("mime_type") or "").lower().startswith("image/")
        ]
    preview = []
    for r in preview_source[: max(0, int(limit))]:
        preview.append(
            {
                "evidence_key": r.get("evidence_key"),
                "type": r.get("attachment_type") or "other",
                "file_url": r.get("file_url"),
                "mime_type": r.get("mime_type") or "",
            }
        )
    return {
        "evidence_count": len(rows),
        "evidence_preview": preview,
    }
