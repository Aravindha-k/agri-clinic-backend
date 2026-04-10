"""
utils/pagination.py
────────────────────
Standard pagination classes for the project.
All classes share the same consistent response envelope:
  { "success": true, "message": "OK", "data": { "count", "next", "previous", "results" } }
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


def _paginated_envelope(paginator, data):
    return Response(
        {
            "success": True,
            "message": "OK",
            "data": {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": data,
            },
        }
    )


class StandardPagination(PageNumberPagination):
    """Default: 50 items / page, max 500."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500

    def get_paginated_response(self, data):
        return _paginated_envelope(self, data)


class LargePagination(PageNumberPagination):
    """For bulk exports: 200 items / page."""

    page_size = 200
    page_size_query_param = "page_size"
    max_page_size = 1000

    def get_paginated_response(self, data):
        return _paginated_envelope(self, data)


class SmallPagination(PageNumberPagination):
    """For notification feeds / short lists: 20 items / page."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return _paginated_envelope(self, data)
