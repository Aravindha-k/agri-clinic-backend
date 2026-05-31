"""JWT authentication with admin inactivity enforcement."""

from __future__ import annotations

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .admin_security import is_admin_user, touch_admin_activity


class AdminJWTAuthentication(JWTAuthentication):
    """Extends JWT auth to enforce admin session inactivity timeout."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, validated_token = result
        if is_admin_user(user):
            check = touch_admin_activity(user, request)
            if not check.ok:
                raise AuthenticationFailed(detail=check.message, code=check.code)
        return user, validated_token
