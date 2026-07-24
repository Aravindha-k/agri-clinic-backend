"""Canonical VisitMedia upload service with client_upload_id idempotency."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from visits.media_validation import (
    MediaValidationError,
    validate_visit_media_file_detailed,
)
from visits.models import Visit, VisitMedia

logger = logging.getLogger(__name__)

# Multipart field names accepted on visit create (in priority order for lists).
INLINE_MEDIA_FILE_KEYS = (
    "media_files",
    "media",
    "files",
    "images",
    "photos",
    "file",
    "image",
    "photo",
    "video",
    "audio",
    "voice",
    "voice_note",
)


class VisitMediaServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "MEDIA_ERROR",
        errors: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.errors = errors or {}


@dataclass
class MediaUploadResult:
    media: VisitMedia
    created: bool
    duplicate: bool


def _infer_media_type_from_file(file) -> str:
    content_type = (getattr(file, "content_type", "") or "").lower()
    name = (getattr(file, "name", "") or "").lower()
    if content_type.startswith("image") or name.endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    ):
        return VisitMedia.MEDIA_TYPE_IMAGE
    if content_type.startswith("video") or name.endswith(
        (".mp4", ".mov", ".m4v", ".3gp")
    ):
        return VisitMedia.MEDIA_TYPE_VIDEO
    if content_type.startswith("audio") or name.endswith(
        (".mp3", ".m4a", ".aac", ".wav", ".ogg")
    ):
        return VisitMedia.MEDIA_TYPE_AUDIO
    if content_type == "application/pdf" or name.endswith(".pdf"):
        return VisitMedia.MEDIA_TYPE_BILL
    return VisitMedia.MEDIA_TYPE_IMAGE


def upload_visit_media(
    *,
    visit: Visit,
    file,
    media_type: str,
    caption: str = "",
    client_upload_id: str | None = None,
    uploaded_by: User | None = None,
    duration_seconds: float | None = None,
) -> MediaUploadResult:
    """
    Canonical VisitMedia writer.

    Replay of the same (visit, client_upload_id) returns the existing row.
    """
    media_type = (media_type or "").strip().lower()
    valid_types = {c[0] for c in VisitMedia.MEDIA_TYPE_CHOICES}
    if media_type not in valid_types:
        raise VisitMediaServiceError(
            f"media_type must be one of: {', '.join(sorted(valid_types))}",
            code="UNSUPPORTED_MEDIA_TYPE",
            errors={"media_type": "Invalid media_type."},
        )
    if not file:
        raise VisitMediaServiceError(
            "file is required.",
            code="INVALID_MEDIA",
            errors={"file": "file is required."},
        )

    try:
        meta = validate_visit_media_file_detailed(
            file_obj=file,
            media_type=media_type,
            client_duration_seconds=duration_seconds,
        )
    except MediaValidationError as exc:
        raise VisitMediaServiceError(
            exc.message,
            code=exc.code,
            errors=exc.errors,
        ) from exc

    upload_id = (client_upload_id or "").strip()
    if upload_id:
        existing = VisitMedia.objects.filter(
            visit=visit, client_upload_id=upload_id
        ).first()
        if existing:
            return MediaUploadResult(media=existing, created=False, duplicate=True)

    owner = uploaded_by or getattr(visit, "employee", None)

    try:
        with transaction.atomic():
            media = VisitMedia.objects.create(
                visit=visit,
                uploaded_by=owner if getattr(owner, "pk", None) else None,
                file=file,
                media_type=media_type,
                caption=caption or "",
                client_upload_id=upload_id,
                mime_type=meta.get("mime_type") or "",
                original_filename=meta.get("original_filename") or "",
                file_size=meta.get("file_size"),
                duration_seconds=meta.get("duration_seconds"),
                processing_status=VisitMedia.STATUS_READY,
            )
        logger.info(
            "event=visit_media_uploaded visit_id=%s media_id=%s type=%s "
            "client_upload_id=%s size=%s",
            visit.pk,
            media.pk,
            media_type,
            upload_id or None,
            meta.get("file_size"),
        )
        return MediaUploadResult(media=media, created=True, duplicate=False)
    except IntegrityError:
        if not upload_id:
            raise
        existing = VisitMedia.objects.filter(
            visit=visit, client_upload_id=upload_id
        ).first()
        if existing:
            return MediaUploadResult(media=existing, created=False, duplicate=True)
        raise


def collect_request_media_files(request) -> list:
    """Collect uploaded files from known multipart field names (deduped)."""
    if not hasattr(request, "FILES"):
        return []
    files = []
    seen_ids = set()
    for key in INLINE_MEDIA_FILE_KEYS:
        for f in request.FILES.getlist(key):
            obj_id = id(f)
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)
            files.append(f)
    return files


def attach_request_media_files(request, visit: Visit) -> None:
    """
    Process multipart media on a create/replay request.

    Accepts media_files / media / file / image / photo / video / audio, etc.
    Raises VisitMediaServiceError on validation failure.
    """
    files = collect_request_media_files(request)
    if not files:
        return

    upload_ids: list[str] = []
    if hasattr(request, "data"):
        raw_ids = request.data.get("media_client_upload_ids") or request.data.get(
            "client_upload_ids"
        )
        if isinstance(raw_ids, list):
            upload_ids = [str(x).strip() for x in raw_ids]
        elif isinstance(raw_ids, str) and raw_ids.strip():
            upload_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]

    explicit_type = ""
    if hasattr(request, "data"):
        explicit_type = (request.data.get("media_type") or "").strip().lower()

    raw_duration = None
    if hasattr(request, "data"):
        raw_duration = request.data.get("duration_seconds")
    duration_seconds = None
    if raw_duration not in (None, ""):
        try:
            duration_seconds = float(raw_duration)
        except (TypeError, ValueError) as exc:
            raise VisitMediaServiceError(
                "Invalid duration_seconds.",
                code="INVALID_MEDIA",
                errors={"duration_seconds": "Invalid duration_seconds."},
            ) from exc

    uploaded_by = getattr(request, "user", None)
    for index, file in enumerate(files):
        media_type = explicit_type if explicit_type in {
            c[0] for c in VisitMedia.MEDIA_TYPE_CHOICES
        } else _infer_media_type_from_file(file)
        client_upload_id = upload_ids[index] if index < len(upload_ids) else ""
        upload_visit_media(
            visit=visit,
            file=file,
            media_type=media_type,
            caption="",
            client_upload_id=client_upload_id or None,
            uploaded_by=uploaded_by if getattr(uploaded_by, "is_authenticated", False) else None,
            duration_seconds=duration_seconds,
        )
