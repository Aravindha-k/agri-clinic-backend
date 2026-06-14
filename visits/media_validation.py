"""Validation helpers for VisitMedia uploads (web + mobile)."""

from __future__ import annotations

import os

MAX_MEDIA_BYTES = 15 * 1024 * 1024  # 15 MB

EXTENSIONS_BY_MEDIA_TYPE: dict[str, set[str]] = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "bill": {".jpg", ".jpeg", ".png", ".webp", ".pdf"},
    "audio": {".mp3", ".m4a", ".wav", ".aac", ".webm", ".ogg"},
    "video": {".mp4", ".mov", ".webm", ".mkv", ".3gp"},
}

ALLOWED_MIME_PREFIXES_BY_MEDIA_TYPE: dict[str, tuple[str, ...]] = {
    "image": ("image/",),
    "bill": ("image/", "application/pdf"),
    "audio": ("audio/",),
    "video": ("video/",),
}


def _file_extension(filename: str) -> str:
    return os.path.splitext((filename or "").lower())[1]


def validate_visit_media_file(*, file_obj, media_type: str) -> dict[str, str]:
    """Return field errors dict; empty dict means valid."""
    errors: dict[str, str] = {}
    media_type = (media_type or "").strip().lower()
    if media_type not in EXTENSIONS_BY_MEDIA_TYPE:
        errors["media_type"] = "media_type must be one of: image, bill, audio, video."
        return errors

    if not file_obj:
        errors["file"] = "file is required."
        return errors

    size = getattr(file_obj, "size", None)
    if size is not None and size > MAX_MEDIA_BYTES:
        errors["file"] = "File size must not exceed 15 MB."

    name = getattr(file_obj, "name", "") or ""
    ext = _file_extension(name)
    allowed_ext = EXTENSIONS_BY_MEDIA_TYPE.get(media_type, set())
    if ext and ext not in allowed_ext:
        errors["file"] = (
            f"File type '{ext}' is not allowed for media_type '{media_type}'."
        )

    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type:
        prefixes = ALLOWED_MIME_PREFIXES_BY_MEDIA_TYPE.get(media_type, ())
        if not any(content_type.startswith(p) for p in prefixes):
            errors["file"] = f"MIME type '{content_type}' is not allowed for '{media_type}'."

    return errors
