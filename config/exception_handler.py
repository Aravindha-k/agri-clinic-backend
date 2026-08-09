from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied
from django.db import IntegrityError, DatabaseError
from django.db.utils import OperationalError
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    # Handle known DRF errors (validation, auth, permission)
    if response is not None:
        code = _extract_exception_code(exc, response.status_code)
        # Deactivated field employees: always 403 with EMPLOYEE_INACTIVE.
        if code == "EMPLOYEE_INACTIVE":
            response.status_code = status.HTTP_403_FORBIDDEN
        errors = response.data if settings.DEBUG else {}
        return Response(
            {
                "success": False,
                "message": _extract_message(response.data),
                "errors": errors,
                "code": code,
            },
            status=response.status_code,
        )

    # Connection / availability errors (e.g. Postgres in recovery mode)
    if isinstance(exc, OperationalError):
        detail = str(exc)
        logger.error("Database unavailable: %s", detail)
        message = "Database is temporarily unavailable. Please retry in a moment."
        if "recovery mode" in detail.lower():
            message = (
                "PostgreSQL is still starting or recovering. "
                "Wait a minute or restart the PostgreSQL service, then retry."
            )
        return Response(
            {
                "success": False,
                "message": message,
                "errors": {"detail": detail} if settings.DEBUG else {},
                "code": "DATABASE_UNAVAILABLE",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, IntegrityError):
        logger.exception("Database integrity error")
        return Response(
            {
                "success": False,
                "message": "A database constraint was violated.",
                "errors": {"detail": str(exc)} if settings.DEBUG else {},
                "code": "DATABASE_ERROR",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, DatabaseError):
        logger.exception("Database error")
        return Response(
            {
                "success": False,
                "message": "A database error occurred.",
                "errors": {"detail": str(exc)} if settings.DEBUG else {},
                "code": "DATABASE_ERROR",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Handle all other errors
    logger.exception("Unhandled server error")
    return Response(
        {
            "success": False,
            "message": "Something went wrong.",
            "errors": {"detail": str(exc)} if settings.DEBUG else {},
            "code": "SERVER_ERROR",
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _extract_message(data) -> str:
    """Pull a human-readable message from DRF error data."""
    if isinstance(data, dict):
        detail = data.get("detail")
        if detail:
            return str(detail)
        # Take first field error
        for value in data.values():
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value)
    if isinstance(data, list) and data:
        return str(data[0])
    return "Request failed"


def _extract_exception_code(exc, http_status: int) -> str:
    auth_code = getattr(exc, "auth_code", None)
    if isinstance(auth_code, str) and auth_code:
        return auth_code
    code = getattr(exc, "default_code", None)
    if isinstance(code, str) and code and code not in {"error", "authentication_failed"}:
        return code
    detail = getattr(exc, "detail", None)
    if detail is not None and hasattr(detail, "code"):
        detail_code = detail.code
        if isinstance(detail_code, str) and detail_code not in {
            None,
            "authentication_failed",
            "permission_denied",
            "not_authenticated",
        }:
            return detail_code
    return _extract_code(http_status)


def _extract_code(http_status: int) -> str:
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        422: "VALIDATION_ERROR",
        409: "DEVICE_SESSION_CONFLICT",
        429: "THROTTLED",
        500: "SERVER_ERROR",
    }
    return mapping.get(http_status, "ERROR")
