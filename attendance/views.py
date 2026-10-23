"""Device-facing attendance APIs (kiosk / future biometric terminal).

All endpoints authenticate via device credentials (X-Device-Id +
X-Device-Token). The shop is always derived from the authenticated device;
client-supplied shop IDs are ignored. Verification method is decided
server-side by the configured BiometricVerifier.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from attendance import devices, services
from attendance.biometrics import BiometricUnavailable, get_verifier
from attendance.models import AttendanceEmployee, AttendanceEvent
from attendance.permissions import HasActiveAttendanceDevice, TestModeEnabled
from attendance.throttling import (
    TrustedScopedRateThrottle,
    global_pairing_attempt_limited,
)
from attendance.serializers import (
    AttendanceEventSerializer,
    AttendanceStatusSerializer,
    EventWriteSerializer,
    SelectableEmployeeSerializer,
)
from utils.response import error_response, success_response

logger = logging.getLogger(__name__)


class DeviceAPIView(APIView):
    """Base class: device credential auth, no user JWT required."""

    authentication_classes = []
    permission_classes = [HasActiveAttendanceDevice]
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = "attendance_device"


class DevicePairingAPI(APIView):
    """Redeem a one-time 6-digit setup code for device credentials.

    Unauthenticated — the code itself is the credential. Short TTL, single
    use (row-locked), attempt-lockout, a per-IP throttle scope and a global
    attempts-per-minute ceiling bound brute force. HTTPS is enforced when
    ATTENDANCE_PAIRING_REQUIRE_HTTPS is set (always in production).
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = "attendance_pairing"

    def post(self, request):
        if getattr(settings, "ATTENDANCE_PAIRING_REQUIRE_HTTPS", False) and not request.is_secure():
            return error_response(
                message="Pairing requires HTTPS.",
                code="PAIRING_HTTPS_REQUIRED",
                status_code=drf_status.HTTP_403_FORBIDDEN,
            )

        max_per_minute = int(getattr(
            settings, "ATTENDANCE_PAIRING_GLOBAL_MAX_PER_MINUTE", 30
        ))
        if global_pairing_attempt_limited(max_per_minute):
            return error_response(
                message="Too many pairing attempts. Try again shortly.",
                code="PAIRING_RATE_LIMITED",
                status_code=drf_status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # `pairing_code` is the documented field; `code` kept for older builds.
        code = str(
            request.data.get("pairing_code") or request.data.get("code") or ""
        ).strip()
        if not (len(code) == 6 and code.isdigit()):
            self._failed(request, "PAIRING_CODE_INVALID")
            return error_response(
                message="Invalid setup code.",
                code="PAIRING_CODE_INVALID",
                status_code=drf_status.HTTP_400_BAD_REQUEST,
            )
        try:
            issued = devices.redeem_pairing_code(
                code, device_label=request.data.get("device_label", "")
            )
        except devices.PairingError as exc:
            self._failed(request, exc.code)
            return error_response(
                message=str(exc), code=exc.code,
                status_code=drf_status.HTTP_403_FORBIDDEN,
            )
        services._audit(
            action="DEVICE_PAIRED", device=issued.device, entity=issued.device,
            metadata={"device_uid": issued.device.device_uid}, request=request,
        )
        shop = issued.device.shop
        return success_response(
            data={
                "device_uid": issued.device.device_uid,
                "device_token": issued.plaintext_token,
                "shop_id": shop.id,
                "shop_code": shop.code,
                "shop_name": shop.name,
                # legacy aliases for already-deployed kiosk builds
                "token": issued.plaintext_token,
                "shop": {"code": shop.code, "name": shop.name},
            },
            message="Device paired.",
            status_code=drf_status.HTTP_200_OK,
        )

    @staticmethod
    def _failed(request, reason: str) -> None:
        """Audit a failed redemption. Never logs the submitted code."""
        services._audit(
            action="PAIRING_FAILED",
            entity=None,
            metadata={"reason": reason},
            request=request,
        )


def _verification_or_403(request, employee):
    """Run the configured verifier. Rejects TEST_MANUAL when test mode is off."""
    verifier = get_verifier()
    try:
        result = verifier.verify(
            employee=employee,
            device=request.attendance_device,
            payload=request.data,
        )
    except BiometricUnavailable:
        return None, error_response(
            message="Biometric verification is not available.",
            code="BIOMETRIC_UNAVAILABLE",
            status_code=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not result.ok:
        services._audit(
            action="FACE_VERIFY_REJECTED",
            device=request.attendance_device,
            entity=employee,
            metadata={
                "employee_code": employee.employee_code,
                "reason": result.detail[:160],
            },
            request=request,
        )
        return None, error_response(
            message="Face verification failed.",
            code="FACE_VERIFICATION_FAILED",
            status_code=drf_status.HTTP_403_FORBIDDEN,
        )
    if result.is_test_mode and not getattr(
        settings, "ATTENDANCE_TEST_MODE_ENABLED", False
    ):
        return None, error_response(
            message="Test-mode attendance is not enabled.",
            code="TEST_MODE_DISABLED",
            status_code=drf_status.HTTP_403_FORBIDDEN,
        )
    return result, None


class _EventAPIBase(DeviceAPIView):
    event_type = None

    def post(self, request):
        serializer = EventWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            employee = AttendanceEmployee.objects.get(pk=data["employee_id"])
        except AttendanceEmployee.DoesNotExist:
            return error_response(
                message="Employee not found.",
                code="EMPLOYEE_NOT_FOUND",
                status_code=drf_status.HTTP_404_NOT_FOUND,
            )
        if not employee.is_active:
            return error_response(
                message="Employee is deactivated and cannot record attendance.",
                code="EMPLOYEE_INACTIVE",
                status_code=drf_status.HTTP_403_FORBIDDEN,
            )

        verification, err = _verification_or_403(request, employee)
        if err:
            return err

        device = request.attendance_device
        try:
            result = services.perform_event(
                employee=employee,
                shop=device.shop,  # shop derived from device, never the client
                device=device,
                event_type=self.event_type,
                verification=verification,
                client_event_id=data.get("client_event_id") or None,
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                request=request,
            )
        except services.AttendanceError as exc:
            return error_response(
                message=str(exc),
                code=exc.code,
                status_code=drf_status.HTTP_409_CONFLICT,
            )

        return success_response(
            data={
                "event": AttendanceEventSerializer(result.event).data,
                "idempotent_replay": result.idempotent_replay,
            },
            message="Attendance recorded.",
            status_code=drf_status.HTTP_201_CREATED
            if not result.idempotent_replay
            else drf_status.HTTP_200_OK,
        )


@extend_schema(tags=["Attendance"], summary="Test-mode check-in")
class AttendanceCheckInAPI(_EventAPIBase):
    event_type = AttendanceEvent.EVENT_CHECK_IN


@extend_schema(tags=["Attendance"], summary="Check-out")
class AttendanceCheckOutAPI(_EventAPIBase):
    event_type = AttendanceEvent.EVENT_CHECK_OUT


@extend_schema(
    tags=["Attendance"],
    summary="Employees selectable at this device (test mode)",
)
class AttendanceEmployeeListAPI(DeviceAPIView):
    permission_classes = [HasActiveAttendanceDevice, TestModeEnabled]

    def get(self, request):
        from django.utils import timezone

        device = request.attendance_device
        today = timezone.localdate()
        qs = (
            AttendanceEmployee.objects.filter(
                shop_assignments__shop=device.shop,
                shop_assignments__is_active=True,
                is_active=True,
            )
            .exclude(shop_assignments__valid_from__gt=today)
            .exclude(shop_assignments__valid_to__lt=today)
            .distinct()
            .order_by("employee_code")
        )
        return success_response(
            data={
                "shop": {"code": device.shop.code, "name": device.shop.name},
                "employees": SelectableEmployeeSerializer(qs, many=True).data,
                "mode": "TEST_MANUAL",
            }
        )


@extend_schema(
    tags=["Attendance"],
    summary="Face enrollments authorized for this device",
)
class FaceEnrollmentListAPI(DeviceAPIView):
    """Kiosk pulls authorized enrollments for ITSELF only.

    Returns employee display fields + enrollment status — never images,
    embeddings or templates (those live encrypted on-device).
    """

    def get(self, request):
        from attendance.models import FaceEnrollment

        device = request.attendance_device
        qs = (
            FaceEnrollment.objects.filter(
                device=device,
                status__in=[
                    FaceEnrollment.STATUS_PENDING,
                    FaceEnrollment.STATUS_ACTIVE,
                ],
                employee__is_active=True,
            )
            .select_related("employee")
            .order_by("employee__employee_code")
        )
        return success_response(
            data={
                "enrollments": [
                    {
                        "enrollment_id": e.id,
                        "employee_id": e.employee_id,
                        "employee_code": e.employee.employee_code,
                        "employee_name": e.employee.full_name,
                        "status": e.status,
                    }
                    for e in qs
                ]
            }
        )


@extend_schema(
    tags=["Attendance"],
    summary="Report face enrollment completed on this device",
)
class FaceEnrollmentCompleteAPI(DeviceAPIView):
    """Device confirms samples captured; flips PENDING → ACTIVE.

    Only metadata (sample_count) is accepted — embeddings never transit.
    """

    def post(self, request, enrollment_id):
        from attendance.models import FaceEnrollment

        device = request.attendance_device
        try:
            enrollment = FaceEnrollment.objects.get(
                pk=enrollment_id,
                status__in=[
                    FaceEnrollment.STATUS_PENDING,
                    FaceEnrollment.STATUS_ACTIVE,
                ],
            )
        except FaceEnrollment.DoesNotExist:
            return error_response(
                message="Enrollment not found.",
                code="ENROLLMENT_NOT_FOUND",
                status_code=drf_status.HTTP_404_NOT_FOUND,
            )
        if enrollment.device_id != device.id:
            return error_response(
                message="Enrollment is bound to a different device.",
                code="ENROLLMENT_WRONG_DEVICE",
                status_code=drf_status.HTTP_403_FORBIDDEN,
            )
        if not enrollment.employee.is_active:
            return error_response(
                message="Employee is not active.",
                code="EMPLOYEE_INACTIVE",
                status_code=drf_status.HTTP_403_FORBIDDEN,
            )
        try:
            sample_count = max(
                0, min(50, int(request.data.get("sample_count", 0)))
            )
        except (TypeError, ValueError):
            sample_count = 0
        if sample_count < 1:
            return error_response(
                message="sample_count must be >= 1.",
                code="ENROLLMENT_NO_SAMPLES",
                status_code=drf_status.HTTP_400_BAD_REQUEST,
            )
        now = timezone.now()
        enrollment.status = FaceEnrollment.STATUS_ACTIVE
        enrollment.sample_count = sample_count
        enrollment.enrolled_at = enrollment.enrolled_at or now
        enrollment.save(
            update_fields=["status", "sample_count", "enrolled_at", "updated_at"]
        )
        services._audit(
            action="ENROLLMENT_COMPLETED",
            device=device,
            entity=enrollment,
            metadata={
                "employee_code": enrollment.employee.employee_code,
                "sample_count": sample_count,
            },
            request=request,
        )
        return success_response(
            data={"enrollment_id": enrollment.id, "status": enrollment.status},
            message="Enrollment completed.",
        )


@extend_schema(tags=["Attendance"], summary="Open attendance status")
class AttendanceStatusAPI(DeviceAPIView):
    def get(self, request):
        serializer = AttendanceStatusSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        device = request.attendance_device
        try:
            employee = AttendanceEmployee.objects.get(
                pk=serializer.validated_data["employee_id"]
            )
        except AttendanceEmployee.DoesNotExist:
            return error_response(
                message="Employee not found.",
                code="EMPLOYEE_NOT_FOUND",
                status_code=drf_status.HTTP_404_NOT_FOUND,
            )
        event = services.open_session(employee, device.shop)
        return success_response(
            data={
                "has_open_session": event is not None,
                "open_event": AttendanceEventSerializer(event).data if event else None,
            }
        )
