"""JWT authentication with admin inactivity + field-employee active enforcement."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings

from accounts.admin_security import is_admin_user, touch_admin_activity
from accounts.employee_access import (
    EMPLOYEE_INACTIVE_CODE,
    EMPLOYEE_INACTIVE_MESSAGE,
    field_employee_may_authenticate,
)


class AdminJWTAuthentication(JWTAuthentication):
    """
    JWT auth with:
    - admin session inactivity timeout
    - field-employee deactivation enforcement (EMPLOYEE_INACTIVE)
    """

    def get_user(self, validated_token):
        """Load user without rejecting inactive accounts (handled in authenticate)."""
        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError as exc:
            raise InvalidToken(
                _("Token contained no recognizable user identification")
            ) from exc

        try:
            user = (
                get_user_model()
                .objects.select_related("employee_profile")
                .get(**{api_settings.USER_ID_FIELD: user_id})
            )
        except get_user_model().DoesNotExist as exc:
            raise AuthenticationFailed(
                _("User not found"), code="user_not_found"
            ) from exc

        return user

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)

        if is_admin_user(user):
            if not user.is_active:
                raise AuthenticationFailed(_("User is inactive"), code="user_inactive")
            check = touch_admin_activity(user, request)
            if not check.ok:
                raise AuthenticationFailed(detail=check.message, code=check.code)
        else:
            # Field employees (and other non-admin JWT users with profiles).
            profile = getattr(user, "employee_profile", None)
            if profile is not None and not field_employee_may_authenticate(user):
                exc = AuthenticationFailed(
                    EMPLOYEE_INACTIVE_MESSAGE,
                    code=EMPLOYEE_INACTIVE_CODE,
                )
                exc.auth_code = EMPLOYEE_INACTIVE_CODE
                raise exc
            if profile is None and not user.is_active:
                raise AuthenticationFailed(_("User is inactive"), code="user_inactive")

        return user, validated_token
