"""Canonical VisitMedia upload service with client_upload_id idempotency."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from visits.media_validation import validate_visit_media_file
from visits.models import Visit, VisitMedia

logger = logging.getLogger(__name__)


class VisitMediaServiceError(Exception):
    def __init__(self, message: str, *, errors: dict | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


@dataclass
class MediaUploadResult:
    media: VisitMedia
    created: bool
    duplicate: bool


def upload_visit_media(
    *,
    visit: Visit,
    file,
    media_type: str,
    caption: str = "",
    client_upload_id: str | None = None,
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
            errors={"media_type": "Invalid media_type."},
        )
    if not file:
        raise VisitMediaServiceError(
            "file is required.",
            errors={"file": "file is required."},
        )

    errors = validate_visit_media_file(file_obj=file, media_type=media_type)
    if errors:
        raise VisitMediaServiceError(
            errors.get("file") or errors.get("media_type", "Invalid media file."),
            errors=errors,
        )

    upload_id = (client_upload_id or "").strip()
    if upload_id:
        existing = VisitMedia.objects.filter(
            visit=visit, client_upload_id=upload_id
        ).first()
        if existing:
            return MediaUploadResult(media=existing, created=False, duplicate=True)

    try:
        with transaction.atomic():
            media = VisitMedia.objects.create(
                visit=visit,
                file=file,
                media_type=media_type,
                caption=caption or "",
                client_upload_id=upload_id,
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


def attach_request_media_files(request, visit: Visit) -> None:
    """
    Process multipart ``media_files`` / ``media`` on a create request.

    Raises VisitMediaServiceError on validation failure.
    Inline uploads without client_upload_id are not replay-deduped by filename.
    """
    if not hasattr(request, "FILES"):
        return
    files = request.FILES.getlist("media_files") or request.FILES.getlist("media")
    if not files:
        return

    for index, file in enumerate(files):
        content_type = (getattr(file, "content_type", "") or "").lower()
        if content_type.startswith("image"):
            media_type = "image"
        elif content_type.startswith("video"):
            media_type = "video"
        elif content_type.startswith("audio"):
            media_type = "audio"
        else:
            media_type = "bill"

        # Prefer explicit parallel client_upload_ids when provided.
        upload_ids = []
        if hasattr(request, "data"):
            raw_ids = request.data.get("media_client_upload_ids") or request.data.get(
                "client_upload_ids"
            )
            if isinstance(raw_ids, list):
                upload_ids = [str(x).strip() for x in raw_ids]
            elif isinstance(raw_ids, str) and raw_ids.strip():
                upload_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]

        client_upload_id = upload_ids[index] if index < len(upload_ids) else ""
        upload_visit_media(
            visit=visit,
            file=file,
            media_type=media_type,
            caption="",
            client_upload_id=client_upload_id or None,
        )
