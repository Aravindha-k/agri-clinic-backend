"""Local/dev-only API to reset test business data (never available in production)."""

import os

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from django.core.management import call_command

from utils.response import error_response, success_response
from utils.schema import error_schema


def _is_production_env() -> bool:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if app_env in {"prod", "production", "render", "staging"}:
        return True
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


@extend_schema(
    tags=["Admin", "Dev"],
    summary="Reset test business data (local/dev only)",
    description=(
        "Deletes visits, media, tracking logs, and safe test farmers. "
        "Never deletes auth users. Disabled when APP_ENV is production."
    ),
    responses={200: None, 403: error_schema("DevResetForbidden")},
)
class DevResetTestBusinessDataAPI(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        if _is_production_env():
            return error_response(
                message="Not available in production.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        include_all = request.data.get("include_all_farmers") in (
            True,
            "true",
            "1",
            1,
        )
        call_command(
            "reset_test_business_data",
            confirm=True,
            include_all_farmers=include_all,
            allow_production=True,
        )
        return success_response(message="Test business data reset complete.")
