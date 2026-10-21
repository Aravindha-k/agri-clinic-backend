"""Device credential issuance and verification.

Tokens are generated with secrets.token_urlsafe; only the SHA-256 hash is
persisted. Plaintext tokens are never stored or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from django.utils import timezone

from attendance.models import AttendanceDevice

TOKEN_PREFIX_LEN = 8


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class IssuedDevice:
    device: AttendanceDevice
    plaintext_token: str  # shown once to the caller; never persisted


def issue_device(
    *,
    shop,
    device_uid: str,
    name: str,
    device_type: str,
    registered_by=None,
) -> IssuedDevice:
    token = generate_device_token()
    device = AttendanceDevice.objects.create(
        shop=shop,
        device_uid=device_uid,
        name=name,
        device_type=device_type,
        token_hash=hash_token(token),
        token_prefix=token[:TOKEN_PREFIX_LEN],
        registered_by=registered_by,
    )
    return IssuedDevice(device=device, plaintext_token=token)


def rotate_device_token(device: AttendanceDevice) -> str:
    """Revoke the current credential and issue a new one. Returns plaintext."""
    token = generate_device_token()
    device.token_hash = hash_token(token)
    device.token_prefix = token[:TOKEN_PREFIX_LEN]
    device.save(update_fields=["token_hash", "token_prefix"])
    return token


def revoke_device(device: AttendanceDevice) -> None:
    device.is_active = False
    device.revoked_at = timezone.now()
    device.save(update_fields=["is_active", "revoked_at"])


def authenticate_device(device_uid: str, token: str) -> AttendanceDevice | None:
    """Return the active device for (uid, token), else None. Constant-time compare."""
    if not device_uid or not token:
        return None
    try:
        device = AttendanceDevice.objects.select_related("shop").get(
            device_uid=device_uid
        )
    except AttendanceDevice.DoesNotExist:
        # Compare against a dummy hash to reduce uid-enumeration timing signal.
        hmac.compare_digest(hash_token(token), "0" * 64)
        return None
    candidate = hash_token(token)
    if not hmac.compare_digest(candidate, device.token_hash):
        return None
    if not device.is_active or not device.shop.is_active:
        return None
    AttendanceDevice.objects.filter(pk=device.pk).update(
        last_seen_at=timezone.now()
    )
    return device
