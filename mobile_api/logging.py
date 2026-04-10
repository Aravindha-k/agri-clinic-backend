import logging
from django.utils.deprecation import MiddlewareMixin


class MobileAPILoggingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.path.startswith("/api/v1/mobile/"):
            user_id = None
            if hasattr(request, "user") and getattr(request, "user", None) is not None:
                user_id = getattr(request.user, "id", None)
            logging.info(
                f"MOBILE API REQUEST: {request.method} {request.path} user={user_id}"
            )
        return None
