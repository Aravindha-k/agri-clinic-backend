"""
utils/response.py
──────────────────
Consistent API response helpers used throughout the project.

SUCCESS  →  { "success": true,  "message": "...", "data": {...} }
ERROR    →  { "success": false, "message": "...", "errors": {...}, "code": "..." }
"""

from rest_framework.response import Response
from rest_framework import status as drf_status


# ──────────────────────────────────────────────────────────────
# Success
# ──────────────────────────────────────────────────────────────


def success_response(
    data=None,
    message: str = "Operation successful",
    status_code: int = drf_status.HTTP_200_OK,
) -> Response:
    return Response(
        {
            "success": True,
            "message": message,
            "data": data if data is not None else {},
        },
        status=status_code,
    )


def created_response(data=None, message: str = "Created successfully") -> Response:
    return success_response(
        data=data, message=message, status_code=drf_status.HTTP_201_CREATED
    )


# ──────────────────────────────────────────────────────────────
# Error
# ──────────────────────────────────────────────────────────────


def error_response(
    message: str = "An error occurred",
    errors=None,
    code: str = "ERROR",
    status_code: int = drf_status.HTTP_400_BAD_REQUEST,
) -> Response:
    return Response(
        {
            "success": False,
            "message": message,
            "errors": errors if errors is not None else {},
            "code": code,
        },
        status=status_code,
    )


def not_found_response(message: str = "Not found") -> Response:
    return error_response(
        message=message, code="NOT_FOUND", status_code=drf_status.HTTP_404_NOT_FOUND
    )


def forbidden_response(message: str = "Permission denied") -> Response:
    return error_response(
        message=message, code="FORBIDDEN", status_code=drf_status.HTTP_403_FORBIDDEN
    )


def validation_error_response(
    errors=None, message: str = "Validation failed"
) -> Response:
    return error_response(
        message=message,
        errors=errors,
        code="VALIDATION_ERROR",
        status_code=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


# ──────────────────────────────────────────────────────────────
# Legacy alias (keep backward-compat for existing code)
# ──────────────────────────────────────────────────────────────


def api_response(
    success: bool = True,
    message: str = "",
    data=None,
    status=None,
) -> Response:
    body = {
        "success": success,
        "message": message,
        "data": data or {},
    }
    return Response(body, status=status) if status else Response(body)
