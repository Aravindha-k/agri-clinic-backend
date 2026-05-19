"""Validation helpers for visit evidence attachments."""

from __future__ import annotations

import mimetypes
import os

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB

ATTACHMENT_TYPE_IMAGE = "image"
ATTACHMENT_TYPE_PDF = "pdf"
ATTACHMENT_TYPE_AUDIO = "audio"
ATTACHMENT_TYPE_TEXT = "text"
ATTACHMENT_TYPE_OTHER = "other"

ATTACHMENT_TYPE_CHOICES = (
    (ATTACHMENT_TYPE_IMAGE, "Image"),
    (ATTACHMENT_TYPE_PDF, "PDF"),
    (ATTACHMENT_TYPE_AUDIO, "Audio"),
    (ATTACHMENT_TYPE_TEXT, "Text note"),
    (ATTACHMENT_TYPE_OTHER, "Other"),
)

EXTENSIONS_BY_TYPE: dict[str, set[str]] = {
    ATTACHMENT_TYPE_IMAGE: {".jpg", ".jpeg", ".png", ".webp"},
    ATTACHMENT_TYPE_PDF: {".pdf"},
    ATTACHMENT_TYPE_AUDIO: {".mp3", ".m4a", ".wav", ".aac", ".webm"},
    ATTACHMENT_TYPE_OTHER: {".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv"},
}

LEGACY_FILE_TYPE_MAP = {
    "CROP": ATTACHMENT_TYPE_IMAGE,
    "SOIL": ATTACHMENT_TYPE_IMAGE,
    "BILL": ATTACHMENT_TYPE_OTHER,
    "VOICE": ATTACHMENT_TYPE_AUDIO,
    "PDF": ATTACHMENT_TYPE_PDF,
    "OTHER": ATTACHMENT_TYPE_OTHER,
}


def normalize_attachment_type(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {choice[0] for choice in ATTACHMENT_TYPE_CHOICES}:
        return raw
    legacy = LEGACY_FILE_TYPE_MAP.get((value or "").strip().upper())
    if legacy:
        return legacy
    return ""


def file_extension(filename: str) -> str:
    return os.path.splitext((filename or "").lower())[1]


def infer_attachment_type(filename: str, mime_type: str = "") -> str:
    ext = file_extension(filename)
    mime = (mime_type or "").lower()
    if ext in EXTENSIONS_BY_TYPE[ATTACHMENT_TYPE_IMAGE] or mime.startswith("image/"):
        return ATTACHMENT_TYPE_IMAGE
    if ext in EXTENSIONS_BY_TYPE[ATTACHMENT_TYPE_PDF] or mime == "application/pdf":
        return ATTACHMENT_TYPE_PDF
    if ext in EXTENSIONS_BY_TYPE[ATTACHMENT_TYPE_AUDIO] or mime.startswith("audio/"):
        return ATTACHMENT_TYPE_AUDIO
    if ext in EXTENSIONS_BY_TYPE[ATTACHMENT_TYPE_OTHER]:
        return ATTACHMENT_TYPE_OTHER
    return ATTACHMENT_TYPE_OTHER


def validate_attachment_payload(
    *,
    attachment_type: str,
    file_obj=None,
    text_content: str | None = None,
) -> dict[str, str]:
    """Return field errors dict; empty dict means valid."""
    errors: dict[str, str] = {}
    attachment_type = normalize_attachment_type(attachment_type)
    if not attachment_type:
        errors["attachment_type"] = (
            "Must be one of: image, pdf, audio, text, other."
        )
        return errors

    text_value = (text_content or "").strip()

    if attachment_type == ATTACHMENT_TYPE_TEXT:
        if not text_value:
            errors["text_content"] = "Text note content is required."
        if file_obj:
            errors["file"] = "File upload is not allowed for text notes."
        return errors

    if not file_obj:
        errors["file"] = "File is required for this attachment type."
        return errors

    size = getattr(file_obj, "size", None)
    if size is not None and size > MAX_ATTACHMENT_BYTES:
        errors["file"] = "File size must not exceed 10 MB."

    name = getattr(file_obj, "name", "") or ""
    ext = file_extension(name)
    allowed = EXTENSIONS_BY_TYPE.get(attachment_type, set())
    if ext and ext not in allowed:
        errors["file"] = (
            f"File type '{ext}' is not allowed for attachment_type '{attachment_type}'."
        )

    content_type = getattr(file_obj, "content_type", "") or ""
    if content_type and not content_type.startswith(
        ("image/", "audio/", "application/", "text/")
    ):
        errors["file"] = f"MIME type '{content_type}' is not allowed."

    return errors


def guess_mime_type(filename: str, content_type: str = "") -> str:
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
