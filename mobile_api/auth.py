from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework import serializers, status
from drf_spectacular.utils import extend_schema
from accounts.models import EmployeeProfile
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
import logging


@extend_schema(
    tags=["Mobile", "Auth"],
    summary="Mobile profile",
    description="Returns the authenticated employee profile details for mobile clients.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("MobileProfileNotFound")},
)
class MobileMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = getattr(user, "employee_profile", None)
        if not profile:
            return error_response(message="Employee profile not found", status_code=404)
        from accounts.employee_photo import employee_me_payload

        return success_response(data=employee_me_payload(request, profile))


class MobileTokenObtainPairSerializer(TokenObtainPairSerializer):
    # Accept employee_id OR username so mobile apps do not need to know Django usernames.
    employee_id = serializers.CharField(required=False, write_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make the username field optional — employee_id can substitute for it.
        self.fields[self.username_field].required = False

    def validate(self, attrs):
        # --- BUG FIX 1: resolve employee_id → username before parent validation ---
        employee_id = attrs.pop("employee_id", None)
        if employee_id:
            try:
                profile = EmployeeProfile.objects.select_related("user").get(
                    employee_id__iexact=employee_id
                )
            except EmployeeProfile.DoesNotExist:
                logging.warning("LOGIN FAILED: employee_id=%s not found", employee_id)
                raise ValidationError({"detail": "Invalid credentials"})
            attrs[self.username_field] = profile.user.username

        if not attrs.get(self.username_field):
            raise ValidationError(
                {self.username_field: "Either username or employee_id is required."}
            )

        data = super().validate(attrs)
        user = self.user

        # --- BUG FIX 2: raise proper exceptions, not Response objects ---
        # Security: Only allow active, non-admin employees
        if not user.is_active:
            logging.warning("LOGIN FAILED: Disabled user %s", user.username)
            raise AuthenticationFailed("Invalid username or password")
        if not hasattr(user, "employee_profile"):
            logging.warning("LOGIN FAILED: No employee profile for %s", user.username)
            raise AuthenticationFailed("Invalid username or password")
        profile = user.employee_profile
        if not profile.is_active_employee:
            logging.warning("LOGIN FAILED: Disabled employee %s", user.username)
            raise AuthenticationFailed("Invalid username or password")
        if user.is_staff:
            logging.warning(
                "LOGIN FAILED: Admin user %s tried mobile login", user.username
            )
            raise AuthenticationFailed("Invalid username or password")

        return {
            "access": data["access"],
            "refresh": data["refresh"],
            "user": {
                "id": user.id,
                "username": user.username,
                "employee_id": profile.employee_id,
                "phone": profile.phone,
                "is_active_employee": profile.is_active_employee,
            },
        }


class MobileTokenObtainPairView(TokenObtainPairView):
    serializer_class = MobileTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # Print the response data to server logs
        import logging

        logging.warning("LOGIN RESPONSE: %s", response.data)
        return response


class MobileTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                return Response(response.data, status=status.HTTP_200_OK)
            # If refresh fails, return 401 so mobile can logout
            return error_response(message="Token refresh failed", status_code=401)
        except Exception as e:
            # Always return 401 for any error in refresh
            from utils.response import error_response

            return error_response(message="Token refresh failed", status_code=401)
