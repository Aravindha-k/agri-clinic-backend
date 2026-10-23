"""Pluggable biometric verification adapter (future fingerprint hardware).

Phase 2 ships only the manual test-mode verifier. A real scanner SDK will
implement BiometricVerifier and be selected via ATTENDANCE_BIOMETRIC_BACKEND.
AttendanceEvent.verification_method records which path produced the event —
clients can never claim BIOMETRIC verification themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from attendance.models import AttendanceEvent


@dataclass
class VerificationResult:
    ok: bool
    method: str
    is_test_mode: bool
    detail: str = ""


class BiometricUnavailable(Exception):
    """Raised when no biometric backend is configured/working."""


class BiometricVerifier(Protocol):
    def verify(self, *, employee, device, payload: dict) -> VerificationResult:
        ...


class ManualTestVerifier:
    """Temporary employee-selection flow. Always TEST_MANUAL."""

    def verify(self, *, employee, device, payload: dict) -> VerificationResult:
        return VerificationResult(
            ok=True,
            method=AttendanceEvent.METHOD_TEST_MANUAL,
            is_test_mode=True,
            detail="manual employee selection (test mode)",
        )


class NullBiometricVerifier:
    """Configured when a biometric backend is selected but unavailable."""

    def verify(self, *, employee, device, payload: dict) -> VerificationResult:
        raise BiometricUnavailable(
            "Biometric verification backend is not available."
        )


class FaceEnrollmentVerifier:
    """Face attendance verification bound to FaceEnrollment records.

    Recognition runs ON the kiosk (MobileFaceNet 1:N over encrypted local
    embeddings); the backend never sees images or templates. The device
    supplies a verification assertion which this verifier checks against
    server-side state — an arbitrary client-supplied employee_id alone is
    never accepted.

    Assertions required in `payload`:
      - employee_id              resolved employee (validated upstream)
      - liveness_confirmed: true  kiosk anti-spoof/liveness flag
      - recognition_score        0..1 confidence >= ATTENDANCE_FACE_MIN_SCORE
      - captured_at              ISO-8601 UTC capture time within
                                 ATTENDANCE_FACE_MAX_SKEW_SECONDS of now
      - capture_nonce            unique per capture (audit trail)

    Additionally requires a FaceEnrollment row in status ACTIVE bound to
    THIS device for this employee. Disabled entirely unless
    ATTENDANCE_FACE_VERIFICATION_ENABLED is set.
    """

    def verify(self, *, employee, device, payload: dict) -> VerificationResult:
        from attendance.models import FaceEnrollment

        if not getattr(settings, "ATTENDANCE_FACE_VERIFICATION_ENABLED", False):
            raise BiometricUnavailable(
                "Face verification is not enabled."
            )

        enrollment = FaceEnrollment.objects.filter(
            employee=employee,
            device=device,
            status=FaceEnrollment.STATUS_ACTIVE,
            enrolled_at__isnull=False,
        ).first()
        if enrollment is None:
            return VerificationResult(
                ok=False,
                method=AttendanceEvent.METHOD_BIOMETRIC,
                is_test_mode=False,
                detail="no active face enrollment for this employee on this device",
            )

        if str(payload.get("liveness_confirmed")).lower() not in {
            "true", "1", "yes",
        }:
            return VerificationResult(
                ok=False,
                method=AttendanceEvent.METHOD_BIOMETRIC,
                is_test_mode=False,
                detail="liveness not confirmed",
            )

        try:
            score = float(payload.get("recognition_score"))
        except (TypeError, ValueError):
            score = -1.0
        min_score = float(
            getattr(settings, "ATTENDANCE_FACE_MIN_SCORE", 0.80)
        )
        if score < min_score:
            return VerificationResult(
                ok=False,
                method=AttendanceEvent.METHOD_BIOMETRIC,
                is_test_mode=False,
                detail=f"recognition score below threshold ({min_score})",
            )

        captured_at = _parse_captured_at(payload.get("captured_at"))
        skew = int(
            getattr(settings, "ATTENDANCE_FACE_MAX_SKEW_SECONDS", 120)
        )
        if captured_at is None or abs(
            (timezone.now() - captured_at).total_seconds()
        ) > skew:
            return VerificationResult(
                ok=False,
                method=AttendanceEvent.METHOD_BIOMETRIC,
                is_test_mode=False,
                detail="capture timestamp missing or outside allowed window",
            )

        return VerificationResult(
            ok=True,
            method=AttendanceEvent.METHOD_BIOMETRIC,
            is_test_mode=False,
            detail="face verified against device enrollment",
        )


def _parse_captured_at(value):
    if not value:
        return None
    try:
        dt = timezone.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(dt):
        return None
    return dt


def get_verifier() -> BiometricVerifier:
    backend = getattr(
        settings, "ATTENDANCE_BIOMETRIC_BACKEND", ""
    ) or "attendance.biometrics.ManualTestVerifier"
    try:
        cls = import_string(backend)
        return cls()
    except Exception:
        return NullBiometricVerifier()
