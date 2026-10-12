"""Server-side live-evidence validation for employee visit photos.

Enforcement rules for employee-submitted VisitMedia:
  * image evidence must declare capture_source="camera" (gallery/file uploads
    are rejected server-side, not only in the app),
  * a fresh GPS fix is required (coordinates + accuracy within a configurable
    limit),
  * the client capture timestamp must be plausible (not in the future, not
    older than a configurable window),
  * the same file may not be reused across different visits by the employee
    (sha-256 dedupe),
  * when a trusted registered field/farmer GPS location exists, the capture
    must be within a configurable radius. The employee-submitted visit
    coordinates are never used as proof of field presence.

All limits are Django-settings tunables with safe defaults.
"""

from __future__ import annotations

import hashlib
import math
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

CAPTURE_SOURCE_CAMERA = "camera"
LIVE_PHOTO_REQUIRED_MESSAGE = (
    "Please capture a live field photo before completing this visit."
)
GPS_RETRY_MESSAGE = (
    "GPS is unavailable or inaccurate. Please move to an open area and retry."
)
EVIDENCE_EXPIRED_MESSAGE = (
    "Evidence is too old or has an invalid capture time. "
    "Please capture a fresh photo."
)
EVIDENCE_REUSED_MESSAGE = "This photo was already used for another visit."
GPS_DISTANCE_MESSAGE = (
    "The capture location is too far from the registered field location."
)


def _setting(name: str, default):
    return getattr(settings, name, default)


def max_accuracy_m() -> float:
    return float(_setting("VISIT_EVIDENCE_MAX_ACCURACY_M", 150.0))


def field_radius_m() -> float:
    return float(_setting("VISIT_EVIDENCE_RADIUS_M", 500.0))


def max_age_minutes() -> float:
    return float(_setting("VISIT_EVIDENCE_MAX_AGE_MINUTES", 60 * 24))


def future_tolerance_minutes() -> float:
    return float(_setting("VISIT_EVIDENCE_FUTURE_TOLERANCE_MINUTES", 15))


def parse_capture_meta(data: Any) -> dict:
    """Normalize capture metadata fields from request.data into a dict."""
    if data is None:
        return {}
    get = data.get if hasattr(data, "get") else (lambda k, d=None: d)

    def _float(key):
        raw = get(key)
        if raw in (None, ""):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    captured_raw = (get("captured_at") or get("captured_at_client") or "").strip()
    captured_at = parse_datetime(captured_raw) if captured_raw else None
    if captured_at is not None and timezone.is_naive(captured_at):
        captured_at = timezone.make_aware(captured_at, timezone.utc)

    return {
        "source": (get("capture_source") or "").strip().lower(),
        "latitude": _float("capture_latitude"),
        "longitude": _float("capture_longitude"),
        "accuracy_m": _float("capture_accuracy_m"),
        "captured_at": captured_at,
    }


def sha256_file(file) -> str:
    """Hash an uploaded file's bytes; restores the read pointer."""
    digest = hashlib.sha256()
    try:
        file.seek(0)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        for chunk in file.chunks():
            digest.update(chunk)
    except (OSError, ValueError):
        raw = file.read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        digest.update(raw or b"")
    try:
        file.seek(0)
    except (OSError, ValueError, AttributeError):
        pass
    return digest.hexdigest()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _parse_gps_pair(raw) -> tuple[float, float] | None:
    if not raw:
        return None
    parts = str(raw).split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    return (lat, lng)


def trusted_visit_gps(visit) -> tuple[float, float] | None:
    """Trusted registered location for the visit's field, then farmer.

    Never returns the employee-submitted visit.latitude/longitude — those are
    not independent proof of field presence.
    """
    field = getattr(visit, "field", None)
    pair = _parse_gps_pair(getattr(field, "gps_location", None))
    if pair:
        return pair
    farmer = getattr(visit, "farmer", None)
    return _parse_gps_pair(getattr(farmer, "gps_location", None))


def validate_live_capture(*, visit, file, meta: dict, employee, error_cls) -> dict:
    """Validate capture metadata + file for an employee image upload.

    ``error_cls`` is raised with (message, code=..., errors=...) on failure so
    callers can convert to a 400. Returns cleaned field values for the row.
    """
    if meta.get("source") != CAPTURE_SOURCE_CAMERA:
        raise error_cls(
            LIVE_PHOTO_REQUIRED_MESSAGE,
            code="LIVE_PHOTO_REQUIRED",
            errors={"file": LIVE_PHOTO_REQUIRED_MESSAGE},
        )

    lat, lng = meta.get("latitude"), meta.get("longitude")
    accuracy = meta.get("accuracy_m")
    if (
        lat is None
        or lng is None
        or accuracy is None
        or accuracy < 0
        or accuracy > max_accuracy_m()
    ):
        raise error_cls(
            GPS_RETRY_MESSAGE,
            code="GPS_REQUIRED",
            errors={"capture_gps": GPS_RETRY_MESSAGE},
        )

    captured_at = meta.get("captured_at")
    now = timezone.now()
    if (
        captured_at is None
        or captured_at > now + timedelta(minutes=future_tolerance_minutes())
        or captured_at < now - timedelta(minutes=max_age_minutes())
    ):
        raise error_cls(
            EVIDENCE_EXPIRED_MESSAGE,
            code="EVIDENCE_EXPIRED",
            errors={"captured_at": EVIDENCE_EXPIRED_MESSAGE},
        )

    file_hash = sha256_file(file)
    from visits.models import VisitAttachment, VisitMedia

    reused = (
        VisitMedia.objects.filter(file_hash=file_hash, uploaded_by=employee)
        .exclude(visit=visit)
        .exists()
        or VisitAttachment.objects.filter(file_hash=file_hash, uploaded_by=employee)
        .exclude(visit=visit)
        .exists()
    )
    if reused:
        raise error_cls(
            EVIDENCE_REUSED_MESSAGE,
            code="EVIDENCE_REUSED",
            errors={"file": EVIDENCE_REUSED_MESSAGE},
        )

    trusted = trusted_visit_gps(visit)
    if trusted and haversine_m(lat, lng, trusted[0], trusted[1]) > field_radius_m():
        raise error_cls(
            GPS_DISTANCE_MESSAGE,
            code="GPS_DISTANCE",
            errors={"capture_gps": GPS_DISTANCE_MESSAGE},
        )

    return {
        "capture_source": CAPTURE_SOURCE_CAMERA,
        "capture_latitude": lat,
        "capture_longitude": lng,
        "capture_accuracy_m": accuracy,
        "captured_at_client": captured_at,
        "file_hash": file_hash,
    }
