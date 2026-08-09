"""Server-side employee username and temporary-password generation."""

from __future__ import annotations

import re
import secrets
import string

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import EmployeeProfile
from .password_policy import validate_strong_password
from .utils import generate_employee_id

USERNAME_PREFIX = "KAC-"
_TEMP_PASSWORD_PREFIX = "Kac@"
_TEMP_PASSWORD_BODY_LEN = 6
_TEMP_PASSWORD_ALPHABET = string.ascii_uppercase + string.digits
_MAX_USERNAME_CREATE_RETRIES = 8

# Ephemeral attribute on EmployeeProfile — never persisted / serialized by default.
TEMPORARY_PASSWORD_ATTR = "_temporary_password"


def normalize_first_name_for_username(first_name: str) -> str:
    """
    Trim, uppercase, drop spaces and non A-Z/0-9 characters.

    \" Aravindh \" -> ARAVINDH
    \"Ravi Kumar\" -> RAVIKUMAR
    """
    raw = (first_name or "").strip().upper()
    raw = raw.replace(" ", "")
    return re.sub(r"[^A-Z0-9]", "", raw)


def _sequence_pattern(base: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(USERNAME_PREFIX)}{re.escape(base)}(\d+)$", re.IGNORECASE)


def next_sequence_for_username_base(base: str) -> int:
    """
    Highest valid sequence for KAC-<BASE><NN> + 1.

    Gaps are ignored (01 + 03 -> next 04). Does not use count()+1.
    """
    if not base:
        raise serializers.ValidationError(
            {"first_name": "First name must contain at least one letter or digit."}
        )
    pattern = _sequence_pattern(base)
    # Broad filter then exact regex — avoids matching KAC-RAVIKUMAR when base=RAVI
    # only via startswith without digit-suffix check.
    candidates = User.objects.filter(
        username__istartswith=f"{USERNAME_PREFIX}{base}"
    ).values_list("username", flat=True)
    max_seq = 0
    for username in candidates:
        match = pattern.match(username or "")
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return max_seq + 1


def generate_employee_username(first_name: str) -> str:
    base = normalize_first_name_for_username(first_name)
    if not base:
        raise serializers.ValidationError(
            {"first_name": "First name must contain at least one letter or digit."}
        )
    seq = next_sequence_for_username_base(base)
    return f"{USERNAME_PREFIX}{base}{seq:02d}"


def generate_temporary_password() -> str:
    """
    Format: Kac@XXXXXX where XXXXXX is secrets-based A-Z / 0-9.

    Guarantees strong-password policy (digit in body; Kac@ supplies lower/upper/special).
    """
    for _ in range(32):
        body = "".join(
            secrets.choice(_TEMP_PASSWORD_ALPHABET)
            for _ in range(_TEMP_PASSWORD_BODY_LEN)
        )
        if not any(ch.isdigit() for ch in body):
            continue
        password = f"{_TEMP_PASSWORD_PREFIX}{body}"
        try:
            validate_strong_password(password)
        except Exception:
            continue
        return password
    raise RuntimeError("Unable to generate temporary password")


def create_field_employee_with_generated_credentials(
    *,
    first_name: str,
    last_name: str = "",
    phone: str = "",
    role: str = "FieldAgent",
    employee_id: str | None = None,
    district_id: int | None = None,
    village_id: int | None = None,
) -> EmployeeProfile:
    """
    Create field employee with auto username + temporary password.

    Retries on username IntegrityError. Never logs the temporary password.
    Attaches plaintext password only on profile._temporary_password for the
    create-response path.
    """
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    if not normalize_first_name_for_username(first_name):
        raise serializers.ValidationError(
            {"first_name": "First name must contain at least one letter or digit."}
        )

    last_error: Exception | None = None
    for _ in range(_MAX_USERNAME_CREATE_RETRIES):
        username = generate_employee_username(first_name)
        temporary_password = generate_temporary_password()
        emp_id = (employee_id or "").strip() or generate_employee_id()
        try:
            with transaction.atomic():
                if EmployeeProfile.objects.filter(employee_id__iexact=emp_id).exists():
                    raise serializers.ValidationError(
                        {"employee_id": "Employee ID already exists"}
                    )
                user = User.objects.create_user(
                    username=username,
                    password=temporary_password,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=False,
                    is_active=True,
                )
                profile = EmployeeProfile.objects.create(
                    user=user,
                    employee_id=emp_id,
                    phone=phone or "",
                    role=role,
                    district_id=district_id,
                    village_id=village_id,
                    is_active_employee=True,
                    can_login=True,
                )
                setattr(profile, TEMPORARY_PASSWORD_ATTR, temporary_password)
                return profile
        except IntegrityError as exc:
            last_error = exc
            # Username (or rare employee_id) collision — retry with next sequence.
            continue
        except serializers.ValidationError:
            raise

    raise serializers.ValidationError(
        {
            "username": (
                "Could not allocate a unique username. Please retry."
                if last_error
                else "Could not create employee."
            )
        }
    )
