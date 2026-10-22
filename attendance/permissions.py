"""Attendance endpoint permissions.

Device endpoints use X-Device-Id + X-Device-Token headers and do NOT require
a user JWT. The resolved device is attached to the request as
`request.attendance_device`; the shop is always derived from the device —
never from client-supplied shop identifiers.
"""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework.permissions import BasePermission

from attendance.devices import authenticate_device
from attendance.models import AttendanceAuditLog, AttendanceDevice

logger = logging.getLogger(__name__)

DEVICE_UID_HEADER = "HTTP_X_DEVICE_ID"
DEVICE_TOKEN_HEADER = "HTTP_X_DEVICE_TOKEN"


def client_ip(request) -> str | None:
    """Client IP for audit/rate limits.

    X-Forwarded-For is trusted only when BEHIND_TRUSTED_PROXY is set (the
    nginx/ELB in front of the app overwrites it). Otherwise a client could
    forge the header to rotate IPs and defeat per-IP throttling.
    """
    from django.conf import settings

    if getattr(settings, "BEHIND_TRUSTED_PROXY", False):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR")
        if fwd:
            return fwd.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR")


_client_ip = client_ip  # backwards-compatible alias


def log_failed_device_auth(request, reason: str) -> None:
    """Record a failed device auth attempt. Never logs token material."""
    AttendanceAuditLog.objects.create(
        action="AUTH_FAILED",
        entity_type="AttendanceDevice",
        entity_id=(request.META.get(DEVICE_UID_HEADER) or "")[:64],
        metadata={"reason": reason},
        ip_address=_client_ip(request),
    )


class HasActiveAttendanceDevice(BasePermission):
    """Allow only requests presenting a valid, active device credential."""

    message = "Invalid or revoked attendance device credentials."
    code = "DEVICE_AUTH_FAILED"

    def has_permission(self, request, view) -> bool:
        device_uid = request.META.get(DEVICE_UID_HEADER, "").strip()
        token = request.META.get(DEVICE_TOKEN_HEADER, "").strip()
        device = authenticate_device(device_uid, token)
        if device is None:
            log_failed_device_auth(request, "bad_credentials_or_inactive")
            return False
        request.attendance_device = device
        return True


class TestModeEnabled(BasePermission):
    """Gate the temporary employee-selection flow behind a setting.

    Enabled by default only outside production; production must set
    ATTENDANCE_TEST_MODE_ENABLED=true explicitly for an authorized pilot.
    """

    message = "Test-mode employee selection is not enabled."
    code = "TEST_MODE_DISABLED"

    def has_permission(self, request, view) -> bool:
        from django.conf import settings

        return bool(getattr(settings, "ATTENDANCE_TEST_MODE_ENABLED", False))
