"""Admin API: two-phase Village + Employee assignment Excel import."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from masters.operational_village_import import (
    VillageImportError,
    collect_plan,
    discard_import_token,
    execute_plan,
    load_and_consume_import_plan,
    store_import_plan,
    validate_upload_file,
)
from utils.permissions import IsStaffAdmin
from utils.response import error_response, success_response


@extend_schema(
    tags=["Admin", "Villages"],
    summary="Validate Village + employee assignment Excel import (no writes)",
)
class VillageImportValidateAPI(APIView):
    """
    POST /api/v1/admin/villages/import/validate/

    multipart/form-data field: file (.xlsx)
    """

    permission_classes = [IsStaffAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get("file")
        try:
            validate_upload_file(upload)
            plan = collect_plan(upload)
        except VillageImportError as exc:
            return error_response(
                message=str(exc),
                errors={"import": [str(exc)]},
                code=exc.code,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = plan.preview_dict()
        import_token = None
        if not plan.has_blocking_errors:
            import_token = store_import_plan(plan=plan, user_id=request.user.pk)
        data["import_token"] = import_token

        message = (
            "Validation completed with blocking errors."
            if plan.has_blocking_errors
            else "Validation completed. Use import_token to confirm."
        )
        return success_response(data=data, message=message)


@extend_schema(
    tags=["Admin", "Villages"],
    summary="Confirm Village + employee assignment Excel import",
)
class VillageImportConfirmAPI(APIView):
    """
    POST /api/v1/admin/villages/import/confirm/

    JSON body: { "import_token": "..." }
    """

    permission_classes = [IsStaffAdmin]

    def post(self, request):
        token = (
            request.data.get("import_token")
            or request.data.get("token")
            or ""
        )
        try:
            plan = load_and_consume_import_plan(
                token=str(token),
                user_id=request.user.pk,
            )
            result = execute_plan(plan)
        except VillageImportError as exc:
            status_code = status.HTTP_400_BAD_REQUEST
            if exc.code in {"TOKEN_FORBIDDEN"}:
                status_code = status.HTTP_403_FORBIDDEN
            elif exc.code in {"TOKEN_INVALID", "TOKEN_REPLAY", "TOKEN_REQUIRED"}:
                status_code = status.HTTP_400_BAD_REQUEST
            return error_response(
                message=str(exc),
                errors={"import_token": [str(exc)]},
                code=exc.code,
                status_code=status_code,
            )
        except Exception:
            # If execute failed after consume, drop token (already consumed).
            discard_import_token(str(token))
            raise

        discard_import_token(str(token))
        return success_response(
            data={
                **result,
                "warnings": [],
                "errors": [],
            },
            message="Import confirmed and applied.",
        )
