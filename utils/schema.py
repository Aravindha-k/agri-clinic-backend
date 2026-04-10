"""
utils/schema.py
----------------
Reusable drf-spectacular helpers for consistent OpenAPI documentation.

Usage:
    from utils.schema import paginated_response_schema, success_schema, error_schema
    from utils.schema import PAGINATION_PARAMS, SEARCH_PARAM, IS_ACTIVE_PARAM
    from utils.schema import SIMPLE_SUCCESS, COMMON_ERROR_RESPONSES
"""

from drf_spectacular.utils import OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers


# ---------------------------------------------------------------
# Common query parameters
# ---------------------------------------------------------------

PAGINATION_PARAMS = [
    OpenApiParameter(
        name="page",
        type=OpenApiTypes.INT,
        location=OpenApiParameter.QUERY,
        description="Page number (1-based).",
        required=False,
    ),
    OpenApiParameter(
        name="page_size",
        type=OpenApiTypes.INT,
        location=OpenApiParameter.QUERY,
        description="Number of results per page (default 50, max varies).",
        required=False,
    ),
]

SEARCH_PARAM = OpenApiParameter(
    name="search",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description="Free-text search across key fields.",
    required=False,
)

IS_ACTIVE_PARAM = OpenApiParameter(
    name="is_active",
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    description="Filter by active status (`true` or `false`).",
    required=False,
)

ORDERING_PARAM = OpenApiParameter(
    name="ordering",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description="Field to sort by. Prefix with `-` for descending.",
    required=False,
)


# ---------------------------------------------------------------
# Standard success envelope:  { success, message, data }
# ---------------------------------------------------------------


def success_schema(name: str, data_properties: dict):
    """
    Wraps arbitrary field dict in the standard success envelope.

    Returns an inline_serializer instance suitable for use in
    extend_schema(responses={200: success_schema(...)}).
    """
    return inline_serializer(
        name=name,
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(),
            "data": inline_serializer(
                name=f"{name}Data",
                fields=data_properties,
            ),
        },
    )


def paginated_response_schema(name: str, result_properties: dict):
    """
    Standard paginated envelope:
      { success, message, data: { count, next, previous, results: [...] } }

    `result_properties` is a dict of field_name -> serializer field instance.
    Uses inline_serializer with many=True for the results list.
    """
    return inline_serializer(
        name=name,
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(default="OK"),
            "data": inline_serializer(
                name=f"{name}Page",
                fields={
                    "count": serializers.IntegerField(),
                    "next": serializers.URLField(allow_null=True),
                    "previous": serializers.URLField(allow_null=True),
                    "results": inline_serializer(
                        name=f"{name}Item",
                        fields=result_properties,
                        many=True,
                    ),
                },
            ),
        },
    )


# ---------------------------------------------------------------
# Standard error envelope:  { success, message, errors, code }
# ---------------------------------------------------------------


_error_schema_cache: dict = {}


def error_schema(name: str = "ErrorResponse"):
    if name not in _error_schema_cache:
        _error_schema_cache[name] = inline_serializer(
            name=name,
            fields={
                "success": serializers.BooleanField(default=False),
                "message": serializers.CharField(),
                "errors": serializers.DictField(
                    child=serializers.JSONField(), default={}
                ),
                "code": serializers.CharField(),
            },
        )
    return _error_schema_cache[name]


# ---------------------------------------------------------------
# Pre-built common schemas
# ---------------------------------------------------------------

COMMON_ERROR_RESPONSES = {
    400: error_schema("BadRequest"),
    401: error_schema("Unauthorized"),
    403: error_schema("Forbidden"),
    404: error_schema("NotFound"),
}

# Simple success with empty data dict (logout, mark-read, etc.)
SIMPLE_SUCCESS = inline_serializer(
    name="SimpleSuccess",
    fields={
        "success": serializers.BooleanField(default=True),
        "message": serializers.CharField(),
        "data": serializers.DictField(default={}),
    },
)
