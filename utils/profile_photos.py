"""Shared validation for employee and farmer profile photos."""

import os

MAX_PROFILE_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB

ALLOWED_PROFILE_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def file_extension(filename: str) -> str:
    return os.path.splitext((filename or "").lower())[1]


def validate_profile_photo(file_obj) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not file_obj:
        errors["profile_photo"] = "Photo file is required."
        return errors

    size = getattr(file_obj, "size", None)
    if size is not None and size > MAX_PROFILE_PHOTO_BYTES:
        errors["profile_photo"] = "Photo must not exceed 5 MB."

    name = getattr(file_obj, "name", "") or ""
    ext = file_extension(name)
    if ext not in ALLOWED_PROFILE_PHOTO_EXTENSIONS:
        errors["profile_photo"] = (
            "Allowed photo types: jpg, jpeg, png, webp."
        )

    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        errors["profile_photo"] = f"Invalid image MIME type: {content_type}"

    return errors
