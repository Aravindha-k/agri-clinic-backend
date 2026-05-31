"""Strong password policy for admin and employee accounts."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


MIN_PASSWORD_LENGTH = 10

_REQUIREMENTS = (
    (r"[a-z]", "at least one lowercase letter"),
    (r"[A-Z]", "at least one uppercase letter"),
    (r"\d", "at least one number"),
    (r"[^A-Za-z0-9]", "at least one special character"),
)


def validate_strong_password(password: str) -> None:
    """Raise ValidationError when password does not meet policy."""
    if password is None:
        raise ValidationError(_("Password is required."))
    errors = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(
            ValidationError(
                _("Password must be at least %(min)d characters long."),
                params={"min": MIN_PASSWORD_LENGTH},
                code="password_too_short",
            )
        )
    for pattern, label in _REQUIREMENTS:
        if not re.search(pattern, password):
            errors.append(
                ValidationError(
                    _("Password must contain %(label)s."),
                    params={"label": label},
                    code="password_too_weak",
                )
            )
    if errors:
        raise ValidationError(errors)


class StrongPasswordValidator:
    """Django AUTH_PASSWORD_VALIDATORS entry."""

    def validate(self, password, user=None):
        validate_strong_password(password)

    def get_help_text(self):
        return _(
            "Password must be at least 10 characters and include uppercase, "
            "lowercase, a number, and a special character."
        )
