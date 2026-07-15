"""Shared JWT refresh validation for web and mobile."""

from __future__ import annotations

import logging

from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.permissions import AllowAny

from accounts.admin_security import issue_tokens_for_user
from accounts.device_sessions import (
    DEVICE_SESSION_HEADER,
    SessionCheckResult,
    check_device_session,
)

logger = logging.getLogger(__name__)

DEVICE_SESSION_CLAIM = "device_session_id"


def _user_from_refresh(refresh: RefreshToken) -> User:
    user_id = refresh.get(jwt_settings.USER_ID_CLAIM)
    if user_id is None:
        raise InvalidToken("Token contained no recognizable user identification")
    user = (
        User.objects.filter(**{jwt_settings.USER_ID_FIELD: user_id})
        .select_related("employee_profile")
        .first()
    )
    if user is None:
        raise AuthenticationFailed("User not found", code="user_not_found")
    return user


def _assert_account_may_refresh(user: User) -> None:
    if not user.is_active:
        raise AuthenticationFailed(
            "Your account is currently disabled. Please contact your administrator.",
            code="ACCOUNT_DISABLED",
        )
    profile = getattr(user, "employee_profile", None)
    if profile is not None and (
        not profile.is_active_employee or not profile.can_login
    ):
        raise AuthenticationFailed(
            "Your account is currently disabled. Please contact your administrator.",
            code="ACCOUNT_DISABLED",
        )


def _resolve_device_session_id(request, refresh: RefreshToken, attrs: dict) -> str | None:
    header_val = None
    if request is not None:
        header_val = request.headers.get(DEVICE_SESSION_HEADER) or request.META.get(
            f"HTTP_{DEVICE_SESSION_HEADER.upper().replace('-', '_')}"
        )
    body_val = attrs.get("device_session_id") or attrs.get("deviceSessionId")
    claim_val = refresh.get(DEVICE_SESSION_CLAIM)
    return header_val or body_val or claim_val


def issue_rotated_tokens(
    user: User, *, device_session_id: str | None = None
) -> dict[str, str]:
    """Issue access+refresh, preserving admin short TTL and optional device claim."""
    refresh, access = issue_tokens_for_user(user)
    if device_session_id:
        refresh[DEVICE_SESSION_CLAIM] = str(device_session_id)
    payload: dict[str, str] = {
        "access": str(access),
        "refresh": str(refresh),
    }
    if device_session_id:
        payload["device_session_id"] = str(device_session_id)
    return payload


class AgriTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Refresh with rotation/blacklist, account-active checks, optional device session.

    Set ``require_device_session=True`` on the owning view for mobile.
    """

    device_session_id = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context.get("request")
        view = self.context.get("view")
        require_device = bool(getattr(view, "require_device_session", False))

        # 1) Parse / verify refresh token (incl. blacklist check on load)
        try:
            refresh = RefreshToken(attrs["refresh"])
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        user = _user_from_refresh(refresh)

        # 2) Device session validation (mobile) — before account checks / new tokens
        device_session_id = _resolve_device_session_id(request, refresh, attrs)
        if require_device:
            result = check_device_session(user, device_session_id)
            if result != SessionCheckResult.OK:
                logger.info(
                    "Refresh rejected user_id=%s device_check=%s",
                    user.pk,
                    result.value,
                )
                raise AuthenticationFailed(
                    "You were logged out because this account was used on another device.",
                    code="SESSION_REPLACED",
                )

        # 3) Account validation
        _assert_account_may_refresh(user)

        # 4) Rotate: blacklist current refresh, then issue new pair
        try:
            refresh.blacklist()
        except AttributeError:
            pass
        except TokenError:
            raise InvalidToken("Token is blacklisted")

        active_device = device_session_id if require_device else refresh.get(
            DEVICE_SESSION_CLAIM
        )
        if not require_device:
            active_device = refresh.get(DEVICE_SESSION_CLAIM)

        data = issue_rotated_tokens(
            user,
            device_session_id=str(active_device) if active_device and require_device else None,
        )
        if require_device and active_device:
            data["device_session_id"] = str(active_device)

        logger.info(
            "Token refresh OK user_id=%s require_device=%s",
            user.pk,
            require_device,
        )
        return data


def attach_device_session_claim(refresh: RefreshToken, session_key) -> RefreshToken:
    refresh[DEVICE_SESSION_CLAIM] = str(session_key)
    return refresh


class AgriWebTokenRefreshView(TokenRefreshView):
    """Web/admin refresh: account-active checks; no device session requirement."""

    permission_classes = [AllowAny]
    serializer_class = AgriTokenRefreshSerializer
    require_device_session = False

    def post(self, request, *args, **kwargs):
        from rest_framework.response import Response
        from rest_framework import status
        from utils.response import error_response

        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed as exc:
            detail = getattr(exc, "detail", None)
            code = getattr(detail, "code", None) if detail is not None else None
            msg = str(detail) if detail is not None else "Authentication failed"
            if code == "ACCOUNT_DISABLED":
                return error_response(
                    message=msg, code="ACCOUNT_DISABLED", status_code=403
                )
            return error_response(
                message="Token refresh failed",
                code=code or "UNAUTHORIZED",
                status_code=401,
            )
        except InvalidToken as exc:
            return error_response(
                message="Token refresh failed",
                code="UNAUTHORIZED",
                status_code=401,
            )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)
