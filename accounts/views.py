from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, FormParser
from utils.response import success_response, error_response
from rest_framework import status

from .models import EmployeeProfile
from .serializers import (
    EmployeeCreateSerializer,
    MeSerializer,
    AdminResetPasswordSerializer,
    AdminCreateSerializer,
    AdminEmployeeListSerializer,
    AdminEmployeeFullCreateSerializer,
    AdminEmployeeUpdateSerializer,
    ChangePasswordSerializer,
)
from .utils import generate_employee_id
from audit_logs.utils import create_audit_log
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

import logging

from django.contrib.auth import authenticate
from rest_framework.permissions import AllowAny

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers
from utils.schema import (
    success_schema,
    paginated_response_schema,
    error_schema,
    PAGINATION_PARAMS,
    SEARCH_PARAM,
    IS_ACTIVE_PARAM,
    SIMPLE_SUCCESS,
    COMMON_ERROR_RESPONSES,
)

try:
    from rest_framework_simplejwt.tokens import RefreshToken

    HAS_SJWT = True
except Exception:
    HAS_SJWT = False

logger = logging.getLogger(__name__)


# ============================
# UNIFIED LOGIN (EMPLOYEE ID / USERNAME)
# ============================
@extend_schema(
    tags=["Auth"],
    summary="Login (employee ID or username)",
    description=(
        "Authenticate with either `employee_id` + `password` or `username` + `password`.  \n"
        "Returns JWT `access` and `refresh` tokens plus employee profile."
    ),
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "example": "KAC-0001"},
                "username": {"type": "string", "example": "john.doe"},
                "password": {"type": "string", "example": "secret"},
            },
            "required": ["password"],
        }
    },
    responses={
        200: {
            "description": "Login successful. Returns JWT tokens and employee data.",
            "content": {
                "application/json": {
                    "example": {
                        "access": "<jwt_access_token>",
                        "refresh": "<jwt_refresh_token>",
                        "user": {"id": 1, "username": "john.doe"},
                        "employee": {
                            "employee_id": "KAC-0001",
                            "name": "John Doe",
                            "role": "FieldAgent",
                        },
                    }
                }
            },
        },
        401: error_schema("LoginUnauthorized"),
        403: error_schema("LoginForbidden"),
    },
    auth=[],
)
class LoginAPI(APIView):
    """
    POST /api/v1/auth/login/
    Accepts either { employee_id, password } or { username, password }.
    """

    permission_classes = [AllowAny]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        logger.info("LOGIN API HIT — path=%s method=%s", request.path, request.method)

        employee_id = None
        username = None

        try:
            data = request.data
            logger.debug(
                "Login request received — data keys: %s",
                list(data.keys()) if hasattr(data, "keys") else "<non-dict>",
            )

            employee_id = data.get("employee_id")
            username = data.get("username")
            password = data.get("password")

            if not password:
                return error_response(
                    message="Password is required",
                    code="VALIDATION_ERROR",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if not employee_id and not username:
                return error_response(
                    message="Either employee_id or username is required",
                    code="VALIDATION_ERROR",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            employee_profile = None

            # ── Resolve employee_id → username ──
            if employee_id:
                logger.info("Login attempt with employee_id=%s", employee_id)
                employee_profile = (
                    EmployeeProfile.objects.select_related(
                        "user", "district", "village"
                    )
                    .filter(employee_id__iexact=employee_id)
                    .first()
                )

                if employee_profile is None:
                    logger.warning(
                        "Login failed: employee_id=%s not found", employee_id
                    )
                    return error_response(
                        message="Employee not found",
                        code="NOT_FOUND",
                        status_code=status.HTTP_401_UNAUTHORIZED,
                    )

                if (
                    not employee_profile.is_active_employee
                    or not employee_profile.can_login
                ):
                    logger.warning(
                        "Login denied for employee_id=%s (active=%s, can_login=%s)",
                        employee_id,
                        employee_profile.is_active_employee,
                        employee_profile.can_login,
                    )
                    return error_response(
                        message="Account is disabled. Contact your administrator.",
                        code="ACCOUNT_DISABLED",
                        status_code=status.HTTP_403_FORBIDDEN,
                    )

                username = employee_profile.user.username
            else:
                logger.info("Login attempt with username=%s", username)

            # ── Admin security pre-checks ──
            from accounts.admin_security import (
                admin_ip_allowed,
                check_account_locked,
                is_admin_user,
                issue_tokens_for_user,
                record_failed_login,
                record_successful_admin_login,
            )

            prospective_user = User.objects.filter(username=username).first()
            if prospective_user and is_admin_user(prospective_user):
                if not admin_ip_allowed(request):
                    logger.warning(
                        "Admin login blocked by IP policy username=%s", username
                    )
                    return error_response(
                        message="Admin login is not allowed from this network.",
                        code="IP_NOT_ALLOWED",
                        status_code=status.HTTP_403_FORBIDDEN,
                    )
                lock_check = check_account_locked(prospective_user)
                if not lock_check.ok:
                    return error_response(
                        message=lock_check.message,
                        code=lock_check.code,
                        status_code=status.HTTP_403_FORBIDDEN,
                    )

            # ── Authenticate ──
            user = authenticate(request=request, username=username, password=password)

            if user is None:
                logger.warning(
                    "Login failed: invalid credentials for username=%s", username
                )
                record_failed_login(prospective_user, username=username or "")
                return error_response(
                    message="Invalid credentials",
                    code="INVALID_CREDENTIALS",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # ── Issue JWT tokens ──
            if not HAS_SJWT:
                logger.error(
                    "SimpleJWT is not available — cannot issue tokens for user=%s",
                    username,
                )
                return error_response(
                    message="Authentication service unavailable",
                    code="SERVER_ERROR",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            try:
                refresh = issue_tokens_for_user(user)
            except Exception as token_err:
                logger.exception(
                    "Token generation failed for user=%s: %s", user.username, token_err
                )
                return error_response(
                    message="Failed to generate authentication token",
                    code="SERVER_ERROR",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # ── Build employee payload (if profile exists) ──
            if employee_profile is None and hasattr(user, "employee_profile"):
                try:
                    employee_profile = EmployeeProfile.objects.select_related(
                        "district", "village"
                    ).get(user=user)
                except EmployeeProfile.DoesNotExist:
                    pass

            employee_data = None
            if employee_profile:
                employee_data = {
                    "id": employee_profile.user.id,
                    "employee_id": employee_profile.employee_id,
                    "name": employee_profile.user.get_full_name()
                    or employee_profile.user.username,
                    "role": employee_profile.role,
                    "region": (
                        employee_profile.district.name
                        if employee_profile.district
                        else None
                    ),
                    "district": (
                        employee_profile.district.name
                        if employee_profile.district
                        else None
                    ),
                    "village": (
                        employee_profile.village.name
                        if employee_profile.village
                        else None
                    ),
                }

            logger.info("Login successful for user=%s (id=%s)", user.username, user.id)

            response_data = {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                },
            }
            if is_admin_user(user):
                response_data["admin"] = record_successful_admin_login(user, request)
            if employee_data:
                response_data["employee"] = employee_data

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as exc:
            logger.exception(
                "Unexpected error in LoginAPI for identifier=%s: %s",
                employee_id or username or "<unknown>",
                exc,
            )
            return error_response(
                message="Login failed due to an unexpected error",
                code="SERVER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ============================
# CREATE EMPLOYEE (ADMIN ONLY)
# ============================
@extend_schema(
    tags=["Employees"],
    summary="Create employee (admin)",
    description="Create a new field employee. Auto-assigns the next KAC-XXXX employee ID.",
    request=EmployeeCreateSerializer,
    responses={
        201: success_schema(
            "CreateEmployeeResponse",
            {"employee_id": drf_serializers.IntegerField()},
        ),
        400: error_schema("CreateEmployeeError"),
    },
)
class CreateEmployeeAPI(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = EmployeeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # ✅ AUDIT LOG (MUST BE BEFORE RETURN)
        create_audit_log(
            actor=request.user,
            module="ACCOUNTS",
            action="CREATE",
            object_id=user.id,
            description="Employee created",
            metadata={"username": user.username},
            request=request,
        )

        return success_response(
            data={"employee_id": user.id},
            message="Employee created successfully",
            status_code=status.HTTP_201_CREATED,
        )


# ============================
# WHO AM I (ADMIN / EMPLOYEE)
# ============================
@extend_schema(
    tags=["Auth"],
    summary="Current user profile",
    description="Returns the authenticated user's profile, role, and employee ID.",
    responses={200: MeSerializer},
)
class MeAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = MeSerializer(request.user)
        return success_response(data=serializer.data)


# ============================
# ADMIN RESET PASSWORD
# ============================
@extend_schema(
    tags=["Employees"],
    summary="Reset employee password (admin)",
    description="Admin forcefully resets an employee's password.",
    request=AdminResetPasswordSerializer,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("ResetPasswordError")},
)
class AdminResetPasswordAPI(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        from audit_logs.utils import create_audit_log

        create_audit_log(
            actor=request.user,
            module="AUTH",
            action="PASSWORD_CHANGE",
            description=f"Admin reset password for {user.username}",
            request=request,
            object_id=user.id,
        )

        return success_response(message="Password reset successfully")


# ============================
# LIST EMPLOYEES (ADMIN ONLY)
# ============================
@extend_schema(
    tags=["Employees"],
    summary="List employees (admin)",
    description="Paginated, searchable list of all employees. Admin only.",
    parameters=[
        *PAGINATION_PARAMS,
        SEARCH_PARAM,
        IS_ACTIVE_PARAM,
        OpenApiParameter(
            "role",
            OpenApiTypes.STR,
            description="Filter by role (e.g. FieldAgent, Supervisor).",
        ),
    ],
    responses={
        200: paginated_response_schema(
            "EmployeeList",
            {
                "id": drf_serializers.IntegerField(),
                "employee_id": drf_serializers.CharField(),
                "name": drf_serializers.CharField(),
                "phone": drf_serializers.CharField(),
                "role": drf_serializers.CharField(),
                "is_active_employee": drf_serializers.BooleanField(),
            },
        )
    },
)
class EmployeeListAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.db.models import Q
        from utils.pagination import StandardPagination

        qs = EmployeeProfile.objects.select_related(
            "user", "district", "village"
        ).order_by("employee_id")

        # Search: name (first/last/username), phone
        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__username__icontains=search)
                | Q(phone__icontains=search)
                | Q(employee_id__icontains=search)
            )

        # Filter: is_active
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active_employee=is_active.lower() == "true")

        # Filter: role
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminEmployeeListSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)


# ============================
# TOGGLE EMPLOYEE STATUS
# ============================
@extend_schema(
    tags=["Employees"],
    summary="Toggle employee active status (legacy)",
    description="Toggle a field employee's active/inactive status by employee string ID. Use the admin endpoint for ID-based access.",
    request=None,
    responses={200: SIMPLE_SUCCESS, 404: error_schema("ToggleNotFound")},
)
class ToggleEmployeeStatusAPI(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, employee_id):
        employee = get_object_or_404(
            EmployeeProfile,
            employee_id=employee_id,
        )

        employee.is_active_employee = not employee.is_active_employee
        employee.user.is_active = employee.is_active_employee

        employee.user.save(update_fields=["is_active"])
        employee.save(update_fields=["is_active_employee"])

        return success_response(
            data={
                "employee_id": employee.employee_id,
                "is_active_employee": employee.is_active_employee,
            }
        )


# ============================
# UPDATE / DELETE EMPLOYEE
# ============================
@extend_schema(
    tags=["Employees"],
    summary="Update or deactivate employee",
    description="PUT/PATCH to update employee details. DELETE soft-deactivates the employee.",
    request=AdminEmployeeUpdateSerializer,
    responses={
        200: AdminEmployeeListSerializer,
        400: error_schema("EmployeeUpdateError"),
        404: error_schema("EmployeeNotFound"),
    },
)
class AdminEmployeeUpdateDeleteAPI(APIView):
    permission_classes = [IsAdminUser]

    def _get_employee(self, pk):
        return get_object_or_404(
            EmployeeProfile.objects.select_related("user", "district"),
            id=pk,
        )

    # FULL UPDATE
    def put(self, request, employee_id):
        employee = self._get_employee(employee_id)
        serializer = AdminEmployeeUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            serializer.update(employee, serializer.validated_data)
        except Exception as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        employee.refresh_from_db()
        return success_response(
            message="Employee updated successfully",
            data=AdminEmployeeListSerializer(employee).data,
        )

    # PARTIAL UPDATE
    def patch(self, request, employee_id):
        employee = self._get_employee(employee_id)
        serializer = AdminEmployeeUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            serializer.update(employee, serializer.validated_data)
        except Exception as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        employee.refresh_from_db()
        return success_response(
            message="Employee updated successfully",
            data=AdminEmployeeListSerializer(employee).data,
        )

    # DELETE (SOFT)
    def delete(self, request, employee_id):
        employee = self._get_employee(employee_id)
        employee.is_active_employee = False
        employee.user.is_active = False
        employee.user.save(update_fields=["is_active"])
        employee.save(update_fields=["is_active_employee"])
        return success_response(
            message="Employee deactivated successfully",
            data=AdminEmployeeListSerializer(employee).data,
        )


@extend_schema(
    tags=["Employees"],
    summary="Create admin user (super-admin only)",
    description="Creates a Django staff/admin user. Requires super-admin privileges.",
    request=AdminCreateSerializer,
    responses={201: SIMPLE_SUCCESS, 403: error_schema("CreateAdminForbidden")},
)
class CreateAdminAPI(APIView):
    """
    Only SUPER ADMIN can create ADMIN users
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_superuser:
            return error_response(
                message="Super Admin only",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = AdminCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        admin = serializer.save()

        return success_response(
            data={"username": admin.username},
            message="Admin created successfully",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Auth"],
    summary="Logout",
    description="Blacklists the refresh token (if SimpleJWT blacklist is enabled) and signals the client to clear stored tokens.",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "refresh": {
                    "type": "string",
                    "description": "Refresh token to blacklist.",
                }
            },
        }
    },
    responses={200: SIMPLE_SUCCESS},
)
class LogoutAPI(APIView):
    """
    Logout endpoint. If refresh token is provided and token blacklist
    is enabled, the token will be blacklisted. Otherwise this endpoint
    simply asks the client to remove stored tokens.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")

        if refresh_token and HAS_SJWT:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                # If blacklist not configured or token invalid, ignore
                pass

        from accounts.admin_security import is_admin_user, record_admin_logout

        if is_admin_user(request.user):
            record_admin_logout(request.user, request)

        return success_response(message="Logged out")


# ============================
# ADMIN EMPLOYEE MANAGEMENT
# RESTful: /api/accounts/admin/employees/
# ============================
@extend_schema(
    tags=["Employees"],
    methods=["GET"],
    summary="Admin — list employees",
    description="Paginated employee list with search, role filter, is_active filter, district filter, and ordering.",
    parameters=[
        *PAGINATION_PARAMS,
        SEARCH_PARAM,
        IS_ACTIVE_PARAM,
        OpenApiParameter("role", OpenApiTypes.STR, description="Filter by role."),
        OpenApiParameter(
            "district_id", OpenApiTypes.INT, description="Filter by district ID."
        ),
        OpenApiParameter(
            "ordering",
            OpenApiTypes.STR,
            description="Sort field. Allowed: employee_id, -employee_id, created_at, -created_at, role, -role.",
        ),
    ],
    responses={200: AdminEmployeeListSerializer(many=True)},
)
@extend_schema(
    tags=["Employees"],
    methods=["POST"],
    summary="Admin — create employee",
    description="Create a new employee with full profile.",
    request=AdminEmployeeFullCreateSerializer,
    responses={201: SIMPLE_SUCCESS, 400: error_schema("AdminCreateEmployeeError")},
)
class AdminEmployeeManagementAPI(APIView):
    """
    GET  /api/accounts/admin/employees/          → list (paginated, searchable)
    POST /api/accounts/admin/employees/          → create
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = EmployeeProfile.objects.select_related(
            "user", "district", "village"
        ).order_by("employee_id")

        # Search
        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(employee_id__icontains=search)
                | Q(user__username__icontains=search)
                | Q(phone__icontains=search)
            )

        # Filters
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)

        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active_employee=is_active.lower() == "true")

        district_id = request.query_params.get("district_id")
        if district_id:
            qs = qs.filter(district_id=district_id)

        # Ordering
        ordering = request.query_params.get("ordering", "employee_id")
        allowed_ordering = {
            "employee_id",
            "-employee_id",
            "created_at",
            "-created_at",
            "role",
            "-role",
        }
        if ordering in allowed_ordering:
            qs = qs.order_by(ordering)

        # Pagination
        paginator = PageNumberPagination()
        paginator.page_size = min(int(request.query_params.get("page_size", 20)), 100)
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminEmployeeListSerializer(
            page, many=True, context={"request": request}
        )
        # Custom paginated response
        paginated_data = paginator.get_paginated_response(serializer.data).data
        return success_response(data=paginated_data)

    def post(self, request):
        serializer = AdminEmployeeFullCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors)

        # Auto-assign district if request user is a district admin
        if not serializer.validated_data.get("district"):
            req_profile = getattr(request.user, "employee_profile", None)
            if req_profile and req_profile.district_id:
                serializer.validated_data["district"] = req_profile.district_id

        try:
            profile = serializer.save()
        except Exception as e:
            return error_response(message=str(e))

        create_audit_log(
            actor=request.user,
            module="ACCOUNTS",
            action="CREATE",
            object_id=profile.user.id,
            description="Employee created (admin management)",
            metadata={"username": profile.user.username, "role": profile.role},
            request=request,
        )

        return success_response(
            data={
                "id": profile.id,
                "username": profile.user.username,
                "employee_id": profile.employee_id,
                "role": profile.role,
                "is_active_employee": profile.is_active_employee,
            },
            message="Employee created (admin management)",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Employees"],
    methods=["GET"],
    summary="Admin — employee detail",
    responses={200: AdminEmployeeListSerializer},
)
@extend_schema(
    tags=["Employees"],
    methods=["PUT"],
    summary="Admin — full update employee",
    request=AdminEmployeeUpdateSerializer,
    responses={200: AdminEmployeeListSerializer, 400: error_schema("AdminUpdateError")},
)
@extend_schema(
    tags=["Employees"],
    methods=["PATCH"],
    summary="Admin — partial update employee",
    request=AdminEmployeeUpdateSerializer,
    responses={200: AdminEmployeeListSerializer, 400: error_schema("AdminPatchError")},
)
class AdminEmployeeDetailAPI(APIView):
    """
    PUT   /api/accounts/admin/employees/{id}/   → full update
    PATCH /api/accounts/admin/employees/{id}/   → partial update
    GET   /api/accounts/admin/employees/{id}/   → single detail
    """

    permission_classes = [IsAdminUser]

    def _get_employee(self, pk):
        return get_object_or_404(
            EmployeeProfile.objects.select_related("user", "district", "village"),
            pk=pk,
        )

    def get(self, request, pk):
        emp = self._get_employee(pk)
        return success_response(data=AdminEmployeeListSerializer(emp).data)

    def put(self, request, pk):
        emp = self._get_employee(pk)
        serializer = AdminEmployeeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.update(emp, serializer.validated_data)
        emp.refresh_from_db()
        return success_response(
            data={"employee": AdminEmployeeListSerializer(emp).data},
            message="Employee updated",
        )

    def patch(self, request, pk):
        emp = self._get_employee(pk)
        serializer = AdminEmployeeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.update(emp, serializer.validated_data)
        emp.refresh_from_db()
        return success_response(
            data={"employee": AdminEmployeeListSerializer(emp).data},
            message="Employee updated",
        )


@extend_schema(
    tags=["Employees"],
    summary="Admin — toggle employee active status",
    description="Atomically toggles `is_active_employee`. Also updates the linked Django user's `is_active` flag. Logs to audit trail.",
    request=None,
    responses={
        200: AdminEmployeeListSerializer,
        404: error_schema("AdminToggleNotFound"),
    },
)
class AdminEmployeeToggleStatusAPI(APIView):
    """
    PATCH /api/accounts/admin/employees/{id}/toggle-status/
    """

    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        emp = get_object_or_404(
            EmployeeProfile.objects.select_related("user", "district"),
            pk=pk,
        )
        emp.is_active_employee = not emp.is_active_employee
        emp.user.is_active = emp.is_active_employee
        emp.user.save(update_fields=["is_active"])
        emp.save(update_fields=["is_active_employee"])

        new_status = "activated" if emp.is_active_employee else "deactivated"
        logger.info(
            "Employee %s %s by admin %s",
            emp.employee_id,
            new_status,
            request.user.username,
        )
        create_audit_log(
            actor=request.user,
            module="ACCOUNTS",
            action="STATUS_CHANGE",
            object_id=emp.id,
            description=f"Employee {emp.employee_id} {new_status}",
            metadata={"is_active_employee": emp.is_active_employee},
            request=request,
        )

        return success_response(
            data=AdminEmployeeListSerializer(emp).data,
            message=f"Employee {new_status} successfully",
        )


# ============================
# SELF-SERVICE PASSWORD CHANGE
# ============================
@extend_schema(
    tags=["Auth"],
    summary="Change own password",
    description="Allows an authenticated employee to change their own password. Requires current password for verification.",
    request=ChangePasswordSerializer,
    responses={200: SIMPLE_SUCCESS, 400: error_schema("ChangePasswordError")},
)
class ChangePasswordAPI(APIView):
    """
    POST /api/v1/employees/change-password/
    Body: { employee_id, current_password, new_password }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save()
        from audit_logs.utils import create_audit_log

        create_audit_log(
            actor=request.user,
            module="AUTH",
            action="PASSWORD_CHANGE",
            description="Employee changed own password",
            request=request,
            object_id=request.user.id,
        )
        return success_response(message="Password updated successfully")


@extend_schema(
    tags=["Auth"],
    summary="Admin security monitoring",
    description="Last login, failed attempts, lockout state, and active admin sessions.",
    responses={200: SIMPLE_SUCCESS},
)
class AdminSecurityMonitoringAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.conf import settings

        from accounts.admin_security import build_admin_security_monitoring_payload

        return success_response(
            data={
                "session_timeout_minutes": settings.ADMIN_SESSION_TIMEOUT_MINUTES,
                "admins": build_admin_security_monitoring_payload(),
            },
            message="Admin security status",
        )
