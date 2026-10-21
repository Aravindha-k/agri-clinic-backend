"""Device-facing attendance APIs (kiosk / future biometric terminal).

All endpoints authenticate via device credentials (X-Device-Id +
X-Device-Token). The shop is always derived from the authenticated device;
client-supplied shop IDs are ignored. Verification method is decided
server-side by the configured BiometricVerifier.
"""

from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status as drf_status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from accounts.models import EmployeeProfile
from attendance import services
from attendance.biometrics import BiometricUnavailable, get_verifier
from attendance.models import AttendanceEvent, EmployeeShopAssignment
from attendance.permissions import HasActiveAttendanceDevice, TestModeEnabled
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_device"


def _verification_or_403(request, employee):
    """Run the configured verifier. Rejects TEST_MANUAL when test mode is off."""
    verifier = get_verifier()
    try:
        result = verifier.verify(
            employee=employee,
            device=request.attendance_device,
            payload=dict(request.data),
        )
    except BiometricUnavailable:
        return None, error_response(
            message="Biometric verification is not available.",
            code="BIOMETRIC_UNAVAILABLE",
            status_code=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
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
            employee = EmployeeProfile.objects.select_related("user").get(
                pk=data["employee_id"], is_active_employee=True
            )
        except EmployeeProfile.DoesNotExist:
            return error_response(
                message="Employee not found or inactive.",
                code="EMPLOYEE_NOT_FOUND",
                status_code=drf_status.HTTP_404_NOT_FOUND,
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
            EmployeeProfile.objects.filter(
                shop_attendance_assignments__shop=device.shop,
                shop_attendance_assignments__is_active=True,
                is_active_employee=True,
                can_login=True,
            )
            .exclude(shop_attendance_assignments__valid_from__gt=today)
            .exclude(
                shop_attendance_assignments__valid_to__lt=today
            )
            .select_related("user")
            .distinct()
            .order_by("employee_id")
        )
        return success_response(
            data={
                "shop": {"code": device.shop.code, "name": device.shop.name},
                "employees": SelectableEmployeeSerializer(qs, many=True).data,
                "mode": "TEST_MANUAL",
            }
        )


@extend_schema(tags=["Attendance"], summary="Open attendance status")
class AttendanceStatusAPI(DeviceAPIView):
    def get(self, request):
        serializer = AttendanceStatusSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        device = request.attendance_device
        try:
            employee = EmployeeProfile.objects.get(
                pk=serializer.validated_data["employee_id"]
            )
        except EmployeeProfile.DoesNotExist:
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
