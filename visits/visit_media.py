"""Attach uploaded media files to a visit (web + admin create)."""

from __future__ import annotations

from rest_framework import status

from utils.response import error_response
from visits.services.media_service import VisitMediaServiceError, attach_request_media_files


def attach_visit_media_files(request, visit) -> error_response | None:
    """
    Process multipart ``media_files`` / ``media`` lists on request.
    Returns an error_response on validation failure, else None.
    """
    try:
        attach_request_media_files(request, visit)
    except VisitMediaServiceError as exc:
        return error_response(
            message=exc.message,
            errors=exc.errors or None,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return None
