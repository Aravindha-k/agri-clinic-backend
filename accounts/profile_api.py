from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from utils.response import success_response, error_response

from accounts.models import EmployeeProfile
from tracking.worklog import WorkLog


class EmployeeProfileAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = getattr(user, "employee_profile", None)
        if not profile:
            return error_response(message="Profile not found", status_code=404)
        work_status = WorkLog.objects.filter(employee=user, is_active=True).exists()
        return success_response(
            data={
                "username": user.username,
                "employee_id": profile.employee_id,
                "phone": profile.phone,
                "work_status": work_status,
            }
        )
