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


def get_verifier() -> BiometricVerifier:
    backend = getattr(
        settings, "ATTENDANCE_BIOMETRIC_BACKEND", ""
    ) or "attendance.biometrics.ManualTestVerifier"
    try:
        cls = import_string(backend)
        return cls()
    except Exception:
        return NullBiometricVerifier()
