"""Request correlation ID middleware."""

from __future__ import annotations

import uuid


class RequestIdMiddleware:
    """Attach X-Request-ID to request and response for structured logs."""

    HEADER = "HTTP_X_REQUEST_ID"
    RESPONSE_HEADER = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(self.HEADER) or str(uuid.uuid4())
        request.request_id = request_id
        response = self.get_response(request)
        response[self.RESPONSE_HEADER] = request_id
        return response
