"""Profile photo upload API views (admin + mobile aliases)."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.employee_photo import employee_me_payload, save_employee_profile_photo
from accounts.models import EmployeeProfile
from accounts.serializers import AdminEmployeeListSerializer
from api.admin.permissions import IsAdminUser
from mobile_api.device_session import DeviceSessionRequiredMixin
from mobile_api.permissions import IsEmployeeUser
from utils.profile_photos import validate_profile_photo
from utils.response import error_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


def _upload_employee_photo_response(request, profile):
    return success_response(
        data=AdminEmployeeListSerializer(profile, context={"request": request}).data,
        message="Employee photo updated",
    )


@extend_schema(
    tags=["Employees"],
    summary="Upload employee profile photo (admin)",
    responses={200: SIMPLE_SUCCESS, 400: error_schema("PhotoValidationError")},
)
class AdminEmployeePhotoAPI(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request, pk):
        profile = get_object_or_404(
            EmployeeProfile.objects.select_related("user"), pk=pk
        )
        file_obj = request.FILES.get("profile_photo") or request.FILES.get("file")
        errors = validate_profile_photo(file_obj)
        if errors:
            return error_response(
                message="Validation failed", errors=errors, status_code=400
            )

        profile = save_employee_profile_photo(profile, file_obj)
        return _upload_employee_photo_response(request, profile)


class EmployeeSelfPhotoAPI(APIView):
    """PATCH employee's own photo — used by mobile and employees/me/photo/ alias."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request):
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return error_response(message="Employee profile not found", status_code=404)

        file_obj = request.FILES.get("profile_photo") or request.FILES.get("file")
        errors = validate_profile_photo(file_obj)
        if errors:
            return error_response(
                message="Validation failed", errors=errors, status_code=400
            )

        profile = save_employee_profile_photo(profile, file_obj)
        return success_response(
            data=employee_me_payload(request, profile),
            message="Profile photo updated",
        )


@extend_schema(
    tags=["Mobile", "Profile"],
    summary="Upload own profile photo (mobile)",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("ProfileNotFound")},
)
class MobileEmployeePhotoAPI(DeviceSessionRequiredMixin, EmployeeSelfPhotoAPI):
    permission_classes = [IsAuthenticated, IsEmployeeUser]


# Backward-compatible names used by older imports
employee_photo_payload = employee_me_payload
_save_employee_photo = save_employee_profile_photo
