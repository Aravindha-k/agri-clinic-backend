"""Device credential issuance and verification.

Tokens are generated with secrets.token_urlsafe; only the SHA-256 hash is
persisted. Plaintext tokens are never stored or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from django.conf import settings
from django.db import IntegrityError, models, transaction
from dataclasses import dataclass

from django.utils import timezone

from attendance.models import AttendanceDevice

TOKEN_PREFIX_LEN = 8


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_pairing_code(code: str) -> str:
    """Keyed HMAC of a pairing code — blind DB reads cannot brute-force it."""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"attendance-pairing:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class IssuedDevice:
    device: AttendanceDevice
    plaintext_token: str  # shown once to the caller; never persisted


DEVICE_UID_MAX_RETRIES = 20


def _new_device_uid() -> str:
    """Permanent 6-digit numeric Device ID. Leading zeros are preserved —
    the UID is stored as a string, never as a number."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _create_device(
    *,
    shop,
    name: str,
    device_type: str,
    token_hash: str,
    token_prefix: str = "",
    is_active: bool = True,
    registered_by=None,
    device_uid: str | None = None,
) -> AttendanceDevice:
    """Insert a device row, auto-generating the 6-digit UID.

    The database unique constraint on device_uid is the ultimate guard; on
    a collision a fresh ID is drawn and retried. An explicit device_uid
    (legacy/test callers only — the admin API never accepts one) is used
    verbatim and is NOT retried.
    """
    for _ in range(DEVICE_UID_MAX_RETRIES):
        try:
            with transaction.atomic():
                return AttendanceDevice.objects.create(
                    shop=shop,
                    device_uid=device_uid or _new_device_uid(),
                    name=name,
                    device_type=device_type,
                    token_hash=token_hash,
                    token_prefix=token_prefix,
                    is_active=is_active,
                    registered_by=registered_by,
                )
        except IntegrityError:
            if device_uid:
                raise
    raise PairingError(
        "Could not allocate a device ID — try again.", "DEVICE_UID_BUSY"
    )


def issue_device(
    *,
    shop,
    name: str,
    device_type: str,
    device_uid: str | None = None,
    registered_by=None,
) -> IssuedDevice:
    token = generate_device_token()
    device = _create_device(
        shop=shop,
        name=name,
        device_type=device_type,
        token_hash=hash_token(token),
        token_prefix=token[:TOKEN_PREFIX_LEN],
        registered_by=registered_by,
        device_uid=device_uid,
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


@dataclass
class IssuedPairingCode:
    device: AttendanceDevice
    plaintext_code: str  # shown once to the admin; only its hash is stored
    expires_at: object


def generate_pairing_code(*, shop, name: str, device_type: str, created_by=None) -> IssuedPairingCode:
    """Create an inactive device + a 6-digit single-use pairing code.

    The device carries a placeholder token hash until redemption, so even a
    leaked pre-pairing record grants nothing. Generating a new code for a
    shop expires its previous unused codes (active-code cap), and a rare
    6-digit collision with a live code simply retries.
    """
    from attendance.models import DevicePairingCode

    now = timezone.now()
    DevicePairingCode.objects.filter(
        device__shop=shop, used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now)

    device = _create_device(
        shop=shop,
        name=name or f"Kiosk @ {shop.code}",
        device_type=device_type,
        token_hash=hash_token(secrets.token_urlsafe(32)),
        token_prefix="",
        is_active=False,
        registered_by=created_by,
    )
    expires_at = now + timezone.timedelta(minutes=DevicePairingCode.TTL_MINUTES)
    for _ in range(5):
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            with transaction.atomic():
                pairing = DevicePairingCode.objects.create(
                    device=device,
                    code_hash=hash_pairing_code(code),
                    code_prefix=code[:2],
                    expires_at=expires_at,
                    created_by=created_by,
                )
            break
        except IntegrityError:
            continue
    else:
        device.delete()
        raise PairingError(
            "Could not allocate a setup code — try again.", "PAIRING_CODE_BUSY"
        )
    return IssuedPairingCode(
        device=device, plaintext_code=code, expires_at=pairing.expires_at
    )


class PairingError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def redeem_pairing_code(code: str, device_label: str = "") -> IssuedDevice:
    """Exchange a valid 6-digit code for live device credentials.

    The pairing row is locked with SELECT ... FOR UPDATE so two concurrent
    requests cannot redeem the same code. Raises PairingError on any failure.
    """
    from attendance.models import DevicePairingCode

    with transaction.atomic():
        pairing = (
            DevicePairingCode.objects.select_for_update()
            .select_related("device__shop")
            .filter(code_hash=hash_pairing_code(code))
            .first()
        )
        if pairing is None:
            raise PairingError("Invalid setup code.", "PAIRING_CODE_INVALID")

        def fail(message: str, err_code: str):
            pairing.attempts = models.F("attempts") + 1
            pairing.save(update_fields=["attempts"])
            raise PairingError(message, err_code)

        if pairing.attempts >= DevicePairingCode.MAX_ATTEMPTS:
            raise PairingError("Setup code locked — generate a new one.", "PAIRING_CODE_LOCKED")
        if pairing.used_at is not None:
            fail("Setup code already used.", "PAIRING_CODE_USED")
        if timezone.now() >= pairing.expires_at:
            fail("Setup code expired.", "PAIRING_CODE_EXPIRED")
        if not pairing.device.shop.is_active:
            fail("Shop is not active.", "PAIRING_SHOP_INACTIVE")

        device = pairing.device
        token = generate_device_token()
        device.token_hash = hash_token(token)
        device.token_prefix = token[:TOKEN_PREFIX_LEN]
        device.is_active = True
        update_fields = ["token_hash", "token_prefix", "is_active"]
        device_label = (device_label or "").strip()[:120]
        if device_label:
            device.name = device_label
            update_fields.append("name")
        pairing.used_at = timezone.now()
        device.save(update_fields=update_fields)
        pairing.save(update_fields=["used_at"])
    return IssuedDevice(device=device, plaintext_token=token)


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
