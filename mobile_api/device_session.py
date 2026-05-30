"""Require valid X-Device-Session for employee mobile APIs."""

from __future__ import annotations

from rest_framework.exceptions import APIException
from rest_framework.views import APIView

from accounts.device_sessions import (
    DEVICE_SESSION_HEADER,
    SessionCheckResult,
    check_device_session,
)
from utils.response import error_response


class SessionReplaced(APIException):
    status_code = 409
    default_code = "SESSION_REPLACED"
    default_detail = (
        "You were logged out because this account was used on another device."
    )


def session_replaced_response():
    return error_response(
        message="You were logged out because this account was used on another device.",
        code="SESSION_REPLACED",
        status_code=409,
    )


class DeviceSessionRequiredMixin:
    """Reject requests without the active device session header (employees only)."""

    require_device_session = True

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.require_device_session and self._should_enforce_device_session(request):
            session_id = request.headers.get(DEVICE_SESSION_HEADER) or request.META.get(
                "HTTP_X_DEVICE_SESSION"
            )
            result = check_device_session(request.user, session_id)
            if result != SessionCheckResult.OK:
                raise SessionReplaced()

    def handle_exception(self, exc):
        if isinstance(exc, SessionReplaced):
            return session_replaced_response()
        return super().handle_exception(exc)

    @staticmethod
    def _should_enforce_device_session(request) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return False
        return hasattr(user, "employee_profile")


class MobileEmployeeAPIView(DeviceSessionRequiredMixin, APIView):
    """Base for authenticated field-employee mobile endpoints."""

    pass
