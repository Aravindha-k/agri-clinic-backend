from drf_spectacular.utils import extend_schema
from rest_framework.parsers import JSONParser
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.employee_photo import employee_me_payload, save_employee_profile_photo
from accounts.serializers import MeSerializer
from tracking.worklog import WorkLog
from utils.profile_photos import validate_profile_photo
from utils.response import error_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


@extend_schema(
    tags=["Employees"],
    summary="Current employee profile",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("ProfileNotFound")},
)
class EmployeeProfileAPI(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return success_response(data=MeSerializer(request.user).data)
        data = employee_me_payload(request, profile)
        data["work_status"] = WorkLog.objects.filter(
            employee=request.user, is_active=True
        ).exists()
        return success_response(data=data)

    def patch(self, request):
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return error_response(message="Profile not found", status_code=404)

        file_obj = request.FILES.get("profile_photo") or request.FILES.get("file")
        if file_obj:
            errors = validate_profile_photo(file_obj)
            if errors:
                return error_response(
                    message="Validation failed", errors=errors, status_code=400
                )
            profile = save_employee_profile_photo(profile, file_obj)

        data = employee_me_payload(request, profile)
        data["work_status"] = WorkLog.objects.filter(
            employee=request.user, is_active=True
        ).exists()
        return success_response(data=data, message="Profile updated")
