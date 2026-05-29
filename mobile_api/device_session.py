"""Require valid X-Device-Session for employee mobile APIs."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.exceptions import APIException

from accounts.device_sessions import DEVICE_SESSION_HEADER, validate_device_session
from utils.response import error_response


class DeviceSessionConflict(APIException):
    status_code = 409
    default_code = "DEVICE_SESSION_CONFLICT"
    default_detail = (
        "Your account is active on another device. Please login again."
    )


def device_session_conflict_response() -> Response:
    return error_response(
        message="Your account is active on another device. Please login again.",
        code="DEVICE_SESSION_CONFLICT",
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
            session = validate_device_session(request.user, session_id)
            if not session:
                raise DeviceSessionConflict()

    def handle_exception(self, exc):
        if isinstance(exc, DeviceSessionConflict):
            return device_session_conflict_response()
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
