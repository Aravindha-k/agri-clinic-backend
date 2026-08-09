from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework import serializers, status
from rest_framework.throttling import ScopedRateThrottle
from drf_spectacular.utils import extend_schema
from accounts.models import EmployeeProfile
from accounts.device_sessions import register_device_session, revoke_user_device_sessions
from accounts.token_refresh import (
    AgriTokenRefreshSerializer,
    issue_rotated_tokens,
)
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from .device_session import DeviceSessionRequiredMixin
import logging

logger = logging.getLogger(__name__)


def _auth_failed(message: str, code: str) -> AuthenticationFailed:
    """AuthenticationFailed whose detail carries a stable machine code."""
    exc = AuthenticationFailed(detail=message, code=code)
    # DRF may wrap string detail; attach code for custom exception handler / view.
    exc.auth_code = code
    return exc


@extend_schema(
    tags=["Mobile", "Auth"],
    summary="Mobile profile",
    description="Returns the authenticated employee profile details for mobile clients.",
    responses={200: SIMPLE_SUCCESS, 404: error_schema("MobileProfileNotFound")},
)
class MobileMeView(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = getattr(user, "employee_profile", None)
        if not profile:
            return error_response(message="Employee profile not found", status_code=404)
        from accounts.employee_photo import employee_me_payload

        return success_response(data=employee_me_payload(request, profile))


@extend_schema(
    tags=["Mobile", "Auth"],
    summary="Mobile bootstrap",
    description=(
        "Canonical authenticated bootstrap: user, device session, current duty, "
        "day-map summary, server_now, feature flags. Full map via /tracking/duty/.../map/."
    ),
    responses={200: SIMPLE_SUCCESS, 409: error_schema("SessionReplaced")},
)
class MobileBootstrapAPI(DeviceSessionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return error_response(message="Employee profile not found", status_code=404)
        from mobile_api.bootstrap import build_mobile_bootstrap

        data = build_mobile_bootstrap(request=request)
        return success_response(data=data, message="Bootstrap")


class MobileTokenObtainPairSerializer(TokenObtainPairSerializer):
    # Accept employee_id OR username so mobile apps do not need to know Django usernames.
    employee_id = serializers.CharField(required=False, write_only=True, allow_blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make the username field optional — employee_id can substitute for it.
        self.fields[self.username_field].required = False

    def validate(self, attrs):
        # Resolve employee_id → username before parent validation
        employee_id = attrs.pop("employee_id", None)
        if isinstance(employee_id, str):
            employee_id = employee_id.strip() or None
        if employee_id:
            try:
                profile = EmployeeProfile.objects.select_related("user").get(
                    employee_id__iexact=employee_id
                )
            except EmployeeProfile.DoesNotExist:
                logging.warning("LOGIN FAILED: employee_id=%s not found", employee_id)
                raise _auth_failed(
                    "Incorrect username or password.",
                    "INVALID_CREDENTIALS",
                )
            attrs[self.username_field] = profile.user.username

        username = attrs.get(self.username_field)
        if isinstance(username, str):
            username = username.strip()
            attrs[self.username_field] = username
        if not username:
            raise ValidationError(
                {self.username_field: "Either username or employee_id is required."}
            )

        # When password is correct, surface account-state codes before JWT's
        # generic "No active account" AuthenticationFailed for inactive users.
        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        candidate = (
            UserModel.objects.filter(username__iexact=username)
            .select_related("employee_profile")
            .first()
        )
        password = attrs.get("password")
        if candidate is not None and candidate.check_password(password or ""):
            if not candidate.is_active:
                logging.warning("LOGIN FAILED: Disabled user %s", candidate.username)
                raise _auth_failed(
                    "Your account has been deactivated. Please contact your administrator.",
                    "EMPLOYEE_INACTIVE",
                )
            if not hasattr(candidate, "employee_profile"):
                logging.warning(
                    "LOGIN FAILED: No employee profile for %s", candidate.username
                )
                raise _auth_failed(
                    "Your employee profile is incomplete. Please contact the administrator.",
                    "EMPLOYEE_PROFILE_MISSING",
                )
            profile = candidate.employee_profile
            if not profile.is_active_employee or not profile.can_login:
                logging.warning(
                    "LOGIN FAILED: Inactive employee %s "
                    "(is_active_employee=%s can_login=%s)",
                    candidate.username,
                    profile.is_active_employee,
                    profile.can_login,
                )
                raise _auth_failed(
                    "Your account has been deactivated. Please contact your administrator.",
                    "EMPLOYEE_INACTIVE",
                )
            if candidate.is_staff:
                logging.warning(
                    "LOGIN FAILED: Admin user %s tried mobile login",
                    candidate.username,
                )
                raise _auth_failed(
                    "Incorrect username or password.",
                    "INVALID_CREDENTIALS",
                )

        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            logging.warning("LOGIN FAILED: invalid password for username=%s", username)
            raise _auth_failed(
                "Incorrect username or password.",
                "INVALID_CREDENTIALS",
            ) from None

        user = self.user

        # Defense in depth (also covered above when password matched).
        if not user.is_active:
            logging.warning("LOGIN FAILED: Disabled user %s", user.username)
            raise _auth_failed(
                "Your account has been deactivated. Please contact your administrator.",
                "EMPLOYEE_INACTIVE",
            )
        if not hasattr(user, "employee_profile"):
            logging.warning("LOGIN FAILED: No employee profile for %s", user.username)
            raise _auth_failed(
                "Your employee profile is incomplete. Please contact the administrator.",
                "EMPLOYEE_PROFILE_MISSING",
            )
        profile = user.employee_profile
        if not profile.is_active_employee or not profile.can_login:
            logging.warning(
                "LOGIN FAILED: Inactive employee %s",
                user.username,
            )
            raise _auth_failed(
                "Your account has been deactivated. Please contact your administrator.",
                "EMPLOYEE_INACTIVE",
            )
        if user.is_staff:
            logging.warning(
                "LOGIN FAILED: Admin user %s tried mobile login", user.username
            )
            raise _auth_failed(
                "Incorrect username or password.",
                "INVALID_CREDENTIALS",
            )

        request = self.context.get("request")
        device_session = register_device_session(
            user,
            request_data=request.data if request else None,
        )
        profile.refresh_from_db()

        # Re-issue tokens with device_session_id claim (parent tokens lack it).
        orphan_refresh = data.get("refresh")
        tokens = issue_rotated_tokens(
            user, device_session_id=str(device_session.session_key)
        )
        if orphan_refresh:
            try:
                RefreshToken(orphan_refresh).blacklist()
            except Exception:
                pass
        return {
            "access": tokens["access"],
            "refresh": tokens["refresh"],
            "device_session_id": str(device_session.session_key),
            "active_device_id": profile.active_device_id,
            "session_version": profile.mobile_session_version,
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
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as exc:
            detail = getattr(exc, "detail", None)
            return error_response(
                message="Please check the login details and try again.",
                code="VALIDATION_ERROR",
                errors=detail if isinstance(detail, dict) else {"detail": detail},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except AuthenticationFailed as exc:
            code = getattr(exc, "auth_code", None) or getattr(exc, "default_code", None)
            if not code or code == "authentication_failed":
                detail = getattr(exc, "detail", None)
                if hasattr(detail, "code") and detail.code not in (None, "authentication_failed"):
                    code = detail.code
                elif isinstance(detail, dict) and isinstance(detail.get("code"), str):
                    code = detail["code"]
                else:
                    code = "INVALID_CREDENTIALS"
            message = str(getattr(exc, "detail", "") or "Authentication failed")
            status_code = (
                status.HTTP_403_FORBIDDEN
                if code
                in {
                    "ACCOUNT_INACTIVE",
                    "EMPLOYEE_INACTIVE",
                    "LOGIN_DISABLED",
                    "EMPLOYEE_PROFILE_MISSING",
                    "ACCOUNT_DISABLED",
                }
                else status.HTTP_401_UNAUTHORIZED
            )
            return error_response(
                message=message,
                code=code,
                status_code=status_code,
            )

        logging.info(
            "Mobile login OK user_id=%s device_session=%s",
            serializer.validated_data.get("user", {}).get("id"),
            bool(serializer.validated_data.get("device_session_id")),
        )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class MobileTokenRefreshView(TokenRefreshView):
    """Mobile refresh: account checks + active device session required."""

    permission_classes = [AllowAny]
    serializer_class = AgriTokenRefreshSerializer
    require_device_session = True
    throttle_scope = "refresh"

    def get_throttles(self):
        return [ScopedRateThrottle()]

    def post(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            try:
                serializer.is_valid(raise_exception=True)
            except AuthenticationFailed as exc:
                detail = getattr(exc, "detail", None)
                code = None
                if hasattr(detail, "code"):
                    code = detail.code
                elif isinstance(detail, dict):
                    code = detail.get("code")
                msg = str(detail) if detail is not None else "Authentication failed"
                if code in {"ACCOUNT_DISABLED", "EMPLOYEE_INACTIVE"}:
                    return error_response(
                        message=msg,
                        code="EMPLOYEE_INACTIVE" if code == "EMPLOYEE_INACTIVE" else code,
                        status_code=403,
                    )
                if code == "SESSION_REPLACED":
                    return error_response(
                        message=msg,
                        code="SESSION_REPLACED",
                        status_code=409,
                    )
                return error_response(
                    message="Token refresh failed",
                    code=code or "UNAUTHORIZED",
                    status_code=401,
                )
            response = Response(serializer.validated_data, status=status.HTTP_200_OK)
            response["Cache-Control"] = "no-store"
            return response
        except Exception:
            return error_response(message="Token refresh failed", status_code=401)


@extend_schema(
    tags=["Mobile", "Auth"],
    summary="Mobile logout",
    description=(
        "Blacklists the refresh token, deactivates EmployeeDeviceSession, "
        "and clears server-side device session state. Does not end DutySession."
    ),
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "refresh": {"type": "string"},
            },
            "required": ["refresh"],
        }
    },
    responses={200: SIMPLE_SUCCESS},
)
class MobileLogoutAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                from rest_framework_simplejwt.settings import (
                    api_settings as jwt_settings,
                )

                token_user_id = token.get(jwt_settings.USER_ID_CLAIM)
                if token_user_id is not None and int(token_user_id) != int(
                    request.user.pk
                ):
                    logger.warning(
                        "Mobile logout rejected foreign refresh user_id=%s token_user=%s",
                        request.user.pk,
                        token_user_id,
                    )
                else:
                    token.blacklist()
            except Exception as exc:
                logger.warning(
                    "Mobile logout blacklist failed user_id=%s err=%s",
                    request.user.pk,
                    exc,
                )

        revoked = revoke_user_device_sessions(request.user, reason="mobile_logout")
        logger.info(
            "Mobile logout user_id=%s sessions_revoked=%s",
            request.user.pk,
            revoked,
        )
        return success_response(message="Logged out")
