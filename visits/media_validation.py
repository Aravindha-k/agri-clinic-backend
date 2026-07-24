"""Validation helpers for VisitMedia uploads (web + mobile)."""

from __future__ import annotations

import logging
import os
import struct
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# Error codes returned to clients
CODE_IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
CODE_AUDIO_TOO_LARGE = "AUDIO_TOO_LARGE"
CODE_VIDEO_TOO_LARGE = "VIDEO_TOO_LARGE"
CODE_BILL_TOO_LARGE = "BILL_TOO_LARGE"
CODE_UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
CODE_VIDEO_DURATION_EXCEEDED = "VIDEO_DURATION_EXCEEDED"
CODE_VIDEO_DURATION_UNKNOWN = "VIDEO_DURATION_UNKNOWN"
CODE_INVALID_MEDIA = "INVALID_MEDIA"

EXTENSIONS_BY_MEDIA_TYPE: dict[str, set[str]] = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "bill": {".jpg", ".jpeg", ".png", ".webp", ".pdf"},
    "audio": {".mp3", ".m4a", ".wav", ".aac", ".ogg"},
    "video": {".mp4", ".mov", ".3gp", ".m4v"},
}

ALLOWED_MIME_BY_MEDIA_TYPE: dict[str, set[str]] = {
    "image": {"image/jpeg", "image/png", "image/webp"},
    "bill": {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
    },
    "audio": {
        "audio/m4a",
        "audio/mp4",
        "audio/aac",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/ogg",
    },
    "video": {
        "video/mp4",
        "video/quicktime",
        "video/3gpp",
        "video/3gpp2",
    },
}

# Legacy prefix fallback when exact MIME is empty / vendor-specific.
ALLOWED_MIME_PREFIXES_BY_MEDIA_TYPE: dict[str, tuple[str, ...]] = {
    "image": ("image/jpeg", "image/png", "image/webp"),
    "bill": ("image/jpeg", "image/png", "image/webp", "application/pdf"),
    "audio": ("audio/",),
    "video": ("video/mp4", "video/quicktime", "video/3gpp"),
}

SIZE_ERROR_BY_TYPE = {
    "image": CODE_IMAGE_TOO_LARGE,
    "audio": CODE_AUDIO_TOO_LARGE,
    "video": CODE_VIDEO_TOO_LARGE,
    "bill": CODE_BILL_TOO_LARGE,
}


class MediaValidationError(Exception):
    def __init__(self, message: str, *, code: str, errors: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.errors = errors or {}


def max_bytes_for_media_type(media_type: str) -> int:
    media_type = (media_type or "").strip().lower()
    mapping = {
        "image": int(getattr(settings, "VISIT_MEDIA_IMAGE_MAX_BYTES", 10 * 1024 * 1024)),
        "audio": int(getattr(settings, "VISIT_MEDIA_AUDIO_MAX_BYTES", 15 * 1024 * 1024)),
        "video": int(getattr(settings, "VISIT_MEDIA_VIDEO_MAX_BYTES", 75 * 1024 * 1024)),
        "bill": int(getattr(settings, "VISIT_MEDIA_BILL_MAX_BYTES", 15 * 1024 * 1024)),
    }
    return mapping.get(media_type, 15 * 1024 * 1024)


def video_max_seconds() -> int:
    return int(getattr(settings, "VISIT_MEDIA_VIDEO_MAX_SECONDS", 60))


def _file_extension(filename: str) -> str:
    return os.path.splitext((filename or "").lower())[1]


def sanitize_original_filename(filename: str) -> str:
    """Strip path components and unsafe characters; never trust client path."""
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    name = name.replace("\x00", "")
    if not name or name in {".", ".."}:
        return "upload.bin"
    # Keep a conservative charset.
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", ".", " "})
    safe = safe.strip(". ") or "upload.bin"
    return safe[:255]


def _read_box_header(data: bytes, offset: int) -> tuple[str, int, int] | None:
    if offset + 8 > len(data):
        return None
    size = struct.unpack(">I", data[offset : offset + 4])[0]
    box_type = data[offset + 4 : offset + 8].decode("latin-1", errors="ignore")
    header = 8
    if size == 1:
        if offset + 16 > len(data):
            return None
        size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
        header = 16
    elif size == 0:
        size = len(data) - offset
    if size < header:
        return None
    return box_type, size, header


def _find_boxes(data: bytes, want: set[str], start: int = 0, end: int | None = None):
    end = len(data) if end is None else end
    offset = start
    while offset + 8 <= end:
        parsed = _read_box_header(data, offset)
        if not parsed:
            break
        box_type, size, header = parsed
        box_end = offset + size
        if box_end > end or size <= 0:
            break
        if box_type in want:
            yield box_type, offset + header, box_end
        if box_type in {"moov", "trak", "mdia", "minf", "stbl"}:
            yield from _find_boxes(data, want, offset + header, box_end)
        offset = box_end


def probe_isobmff_duration_seconds(file_obj) -> float | None:
    """
    Read duration from ISO BMFF (mp4/m4a/mov) mdhd atom.
    Returns None when duration cannot be determined.
    """
    try:
        pos = file_obj.tell() if hasattr(file_obj, "tell") else None
    except Exception:
        pos = None
    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        # Cap read — duration lives early in moov for typical mobile exports.
        data = file_obj.read(8 * 1024 * 1024)
        if not data or len(data) < 16:
            return None
        for box_type, payload_start, payload_end in _find_boxes(data, {"mdhd"}):
            payload = data[payload_start:payload_end]
            if len(payload) < 20:
                continue
            version = payload[0]
            if version == 0 and len(payload) >= 20:
                timescale = struct.unpack(">I", payload[12:16])[0]
                duration = struct.unpack(">I", payload[16:20])[0]
            elif version == 1 and len(payload) >= 32:
                timescale = struct.unpack(">I", payload[20:24])[0]
                duration = struct.unpack(">Q", payload[24:32])[0]
            else:
                continue
            if timescale <= 0:
                continue
            return float(duration) / float(timescale)
        return None
    except Exception:
        logger.debug("ISO BMFF duration probe failed", exc_info=True)
        return None
    finally:
        try:
            if hasattr(file_obj, "seek"):
                if pos is not None:
                    file_obj.seek(pos)
                else:
                    file_obj.seek(0)
        except Exception:
            pass


def probe_media_duration_seconds(*, file_obj, media_type: str, mime_type: str = "") -> float | None:
    media_type = (media_type or "").strip().lower()
    mime = (mime_type or getattr(file_obj, "content_type", "") or "").lower()
    name = (getattr(file_obj, "name", "") or "").lower()
    if media_type in {"video", "audio"} or mime.startswith(("video/", "audio/")):
        if (
            mime in {"video/mp4", "video/quicktime", "audio/mp4", "audio/m4a", "audio/aac"}
            or name.endswith((".mp4", ".m4a", ".mov", ".m4v", ".3gp"))
            or media_type in {"video", "audio"}
        ):
            return probe_isobmff_duration_seconds(file_obj)
    return None


def validate_visit_media_file(
    *,
    file_obj,
    media_type: str,
    client_duration_seconds: float | None = None,
) -> dict[str, str]:
    """
    Return field errors dict; empty dict means valid.

    Prefer validate_visit_media_file_detailed for coded errors.
    """
    try:
        validate_visit_media_file_detailed(
            file_obj=file_obj,
            media_type=media_type,
            client_duration_seconds=client_duration_seconds,
        )
        return {}
    except MediaValidationError as exc:
        return {k: v for k, v in (exc.errors or {"file": exc.message}).items()}


def validate_visit_media_file_detailed(
    *,
    file_obj,
    media_type: str,
    client_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Validate media and return metadata dict:
    mime_type, file_size, duration_seconds, original_filename
    Raises MediaValidationError with machine-readable code.
    """
    media_type = (media_type or "").strip().lower()
    if media_type not in EXTENSIONS_BY_MEDIA_TYPE:
        raise MediaValidationError(
            "media_type must be one of: image, bill, audio, video.",
            code=CODE_UNSUPPORTED_MEDIA_TYPE,
            errors={"media_type": "media_type must be one of: image, bill, audio, video."},
        )

    if not file_obj:
        raise MediaValidationError(
            "file is required.",
            code=CODE_INVALID_MEDIA,
            errors={"file": "file is required."},
        )

    original_filename = sanitize_original_filename(getattr(file_obj, "name", "") or "")
    size = getattr(file_obj, "size", None)
    max_bytes = max_bytes_for_media_type(media_type)
    if size is not None and size > max_bytes:
        mb = max_bytes / (1024 * 1024)
        code = SIZE_ERROR_BY_TYPE.get(media_type, CODE_INVALID_MEDIA)
        raise MediaValidationError(
            f"{media_type.title()} file must not exceed {mb:g} MB.",
            code=code,
            errors={"file": f"File size must not exceed {mb:g} MB."},
        )

    ext = _file_extension(original_filename)
    allowed_ext = EXTENSIONS_BY_MEDIA_TYPE.get(media_type, set())
    if ext and ext not in allowed_ext:
        raise MediaValidationError(
            f"File type '{ext}' is not allowed for media_type '{media_type}'.",
            code=CODE_UNSUPPORTED_MEDIA_TYPE,
            errors={
                "file": f"File type '{ext}' is not allowed for media_type '{media_type}'."
            },
        )

    content_type = (getattr(file_obj, "content_type", "") or "").lower().strip()
    allowed_exact = ALLOWED_MIME_BY_MEDIA_TYPE.get(media_type, set())
    if content_type:
        ok = content_type in allowed_exact
        if not ok and media_type == "audio" and content_type.startswith("audio/"):
            # Accept common Android audio/* variants after extension check.
            ok = True
        if not ok and media_type == "video":
            ok = any(
                content_type.startswith(p)
                for p in ("video/mp4", "video/quicktime", "video/3gpp")
            )
        if not ok and media_type in {"image", "bill"}:
            ok = content_type in allowed_exact
        if not ok:
            raise MediaValidationError(
                f"MIME type '{content_type}' is not allowed for '{media_type}'.",
                code=CODE_UNSUPPORTED_MEDIA_TYPE,
                errors={
                    "file": f"MIME type '{content_type}' is not allowed for '{media_type}'."
                },
            )
    else:
        # No client MIME — require a recognized extension.
        if not ext or ext not in allowed_ext:
            raise MediaValidationError(
                "Unable to determine a supported media type.",
                code=CODE_UNSUPPORTED_MEDIA_TYPE,
                errors={"file": "Unable to determine a supported media type."},
            )
        # Infer MIME from extension when client omitted content_type.
        content_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".mp4": "video/mp4",
            ".m4v": "video/mp4",
            ".mov": "video/quicktime",
            ".3gp": "video/3gpp",
        }.get(ext, "")

    duration_seconds = None
    if media_type == "video":
        probed = probe_media_duration_seconds(
            file_obj=file_obj, media_type=media_type, mime_type=content_type
        )
        if probed is not None:
            duration_seconds = probed
        elif client_duration_seconds is not None:
            try:
                duration_seconds = float(client_duration_seconds)
            except (TypeError, ValueError) as exc:
                raise MediaValidationError(
                    "Invalid duration_seconds.",
                    code=CODE_INVALID_MEDIA,
                    errors={"duration_seconds": "Invalid duration_seconds."},
                ) from exc
        else:
            raise MediaValidationError(
                "Unable to determine video duration. Upload a valid MP4/MOV under 60 seconds.",
                code=CODE_VIDEO_DURATION_UNKNOWN,
                errors={"file": "Unable to determine video duration."},
            )

        max_secs = video_max_seconds()
        if duration_seconds > max_secs + 0.05:
            raise MediaValidationError(
                "Video must be 60 seconds or shorter.",
                code=CODE_VIDEO_DURATION_EXCEEDED,
                errors={"file": "Video must be 60 seconds or shorter."},
            )
    elif media_type == "audio":
        probed = probe_media_duration_seconds(
            file_obj=file_obj, media_type=media_type, mime_type=content_type
        )
        if probed is not None:
            duration_seconds = probed
        elif client_duration_seconds is not None:
            try:
                duration_seconds = float(client_duration_seconds)
            except (TypeError, ValueError):
                duration_seconds = None

    # Reject obvious path traversal / executable names.
    lower_name = original_filename.lower()
    if ".." in (getattr(file_obj, "name", "") or "") or lower_name.endswith(
        (".exe", ".bat", ".cmd", ".sh", ".js", ".html", ".htm", ".php")
    ):
        raise MediaValidationError(
            "Executable or unsafe file types are not allowed.",
            code=CODE_UNSUPPORTED_MEDIA_TYPE,
            errors={"file": "Executable or unsafe file types are not allowed."},
        )

    return {
        "mime_type": content_type,
        "file_size": int(size) if size is not None else None,
        "duration_seconds": duration_seconds,
        "original_filename": original_filename,
    }
