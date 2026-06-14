"""Attach uploaded media files to a visit (web + admin create)."""

from __future__ import annotations

from rest_framework import status

from utils.response import error_response
from visits.media_validation import validate_visit_media_file
from visits.models import VisitMedia


def attach_visit_media_files(request, visit) -> error_response | None:
    """
    Process multipart ``media_files`` / ``media`` lists on request.
    Returns an error_response on validation failure, else None.
    """
    files = []
    if hasattr(request, "FILES"):
        files = request.FILES.getlist("media_files") or request.FILES.getlist("media")
    if not files:
        return None

    for file in files:
        content_type = (getattr(file, "content_type", "") or "").lower()
        if content_type.startswith("image"):
            media_type = "image"
        elif content_type.startswith("video"):
            media_type = "video"
        elif content_type.startswith("audio"):
            media_type = "audio"
        else:
            media_type = "bill"
        errors = validate_visit_media_file(file_obj=file, media_type=media_type)
        if errors:
            return error_response(
                message=errors.get("file")
                or errors.get("media_type", "Invalid media file."),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        VisitMedia.objects.create(visit=visit, file=file, media_type=media_type)
    return None
