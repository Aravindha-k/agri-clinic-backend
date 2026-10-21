"""Staff admin APIs: shops, devices, assignments, shifts, reports, audit log."""

from __future__ import annotations

import logging

from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from attendance.admin_serializers import (
    AdminAttendanceEventSerializer,
    AttendanceAuditLogSerializer,
    AttendanceDailySummarySerializer,
    AttendanceDeviceSerializer,
    AttendanceEmployeeSerializer,
    EmployeeShopAssignmentSerializer,
    ShiftSerializer,
    ShopSerializer,
)
from attendance.devices import issue_device, revoke_device, rotate_device_token
from attendance.models import (
    AttendanceAuditLog,
    AttendanceDailySummary,
    AttendanceDevice,
    AttendanceEmployee,
    AttendanceEvent,
    EmployeeShopAssignment,
    Shift,
    Shop,
)
from attendance.services import _audit
from utils.permissions import IsStaffAdmin
from utils.response import created_response, error_response, success_response

logger = logging.getLogger(__name__)


class AdminAttendanceBase:
    permission_classes = [IsStaffAdmin]


class ShopViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    queryset = Shop.objects.all()
    serializer_class = ShopSerializer
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]

    def perform_create(self, serializer):
        obj = serializer.save()
        _audit(action="SHOP_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        _audit(action="SHOP_SAVED", actor=self.request.user, entity=obj,
               request=self.request)


class AttendanceDeviceViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    """Device lifecycle. Token is returned once at registration/rotation."""

    queryset = AttendanceDevice.objects.select_related("shop", "registered_by")
    serializer_class = AttendanceDeviceSerializer
    search_fields = ["device_uid", "name"]
    filterset_fields = ["is_active", "device_type", "shop"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued = issue_device(
            shop=serializer.validated_data["shop"],
            device_uid=serializer.validated_data["device_uid"],
            name=serializer.validated_data["name"],
            device_type=serializer.validated_data.get(
                "device_type", AttendanceDevice.DEVICE_KIOSK
            ),
            registered_by=request.user,
        )
        _audit(
            action="DEVICE_REGISTERED",
            actor=request.user,
            device=issued.device,
            entity=issued.device,
            request=request,
        )
        return created_response(
            data={
                "device": AttendanceDeviceSerializer(issued.device).data,
                "token": issued.plaintext_token,  # shown once only
            },
            message="Device registered. Store the token securely — it will not be shown again.",
        )

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        device = self.get_object()
        revoke_device(device)
        _audit(action="DEVICE_REVOKED", actor=request.user, device=device,
               entity=device, request=request)
        return success_response(
            data={"device": AttendanceDeviceSerializer(device).data},
            message="Device revoked.",
        )

    @action(detail=True, methods=["post"])
    def rotate(self, request, pk=None):
        device = self.get_object()
        token = rotate_device_token(device)
        _audit(action="DEVICE_ROTATED", actor=request.user, device=device,
               entity=device, request=request)
        return success_response(
            data={"device": AttendanceDeviceSerializer(device).data, "token": token},
            message="Device token rotated. Store the new token securely.",
        )


class AttendanceEmployeeViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    """Admin CRUD for attendance-only employees.

    These identities have no Django user and no Field Officer access.
    Deactivation blocks new attendance events but preserves history.
    """

    queryset = AttendanceEmployee.objects.select_related(
        "linked_profile", "created_by", "updated_by"
    )
    serializer_class = AttendanceEmployeeSerializer
    search_fields = ["employee_code", "full_name", "phone"]
    filterset_fields = ["is_active"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        _audit(action="EMPLOYEE_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save(updated_by=self.request.user)
        _audit(action="EMPLOYEE_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    def destroy(self, request, *args, **kwargs):
        return error_response(
            message="Employees are deactivated, not deleted — attendance history must be preserved.",
            code="DELETE_NOT_ALLOWED",
            status_code=405,
        )

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = False
        employee.updated_by = request.user
        employee.save(update_fields=["is_active", "updated_by", "updated_at"])
        _audit(action="EMPLOYEE_DEACTIVATED", actor=request.user, entity=employee,
               request=request)
        return success_response(
            data=AttendanceEmployeeSerializer(employee).data,
            message="Employee deactivated.",
        )

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = True
        employee.updated_by = request.user
        employee.save(update_fields=["is_active", "updated_by", "updated_at"])
        _audit(action="EMPLOYEE_ACTIVATED", actor=request.user, entity=employee,
               request=request)
        return success_response(
            data=AttendanceEmployeeSerializer(employee).data,
            message="Employee activated.",
        )


class EmployeeShopAssignmentViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    queryset = EmployeeShopAssignment.objects.select_related(
        "employee", "shop", "shift"
    )
    serializer_class = EmployeeShopAssignmentSerializer
    filterset_fields = ["is_active", "shop", "employee", "shift"]

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        _audit(action="ASSIGNMENT_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    def perform_update(self, serializer):
        old_shop_id = self.get_object().shop_id
        obj = serializer.save()
        if obj.shop_id != old_shop_id:
            _audit(
                action="EMPLOYEE_TRANSFERRED",
                actor=self.request.user,
                entity=obj,
                metadata={
                    "employee_code": obj.employee.employee_code,
                    "from_shop_id": old_shop_id,
                    "to_shop_id": obj.shop_id,
                },
                request=self.request,
            )
        else:
            _audit(action="ASSIGNMENT_SAVED", actor=self.request.user, entity=obj,
                   request=self.request)


class ShiftViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    queryset = Shift.objects.select_related("shop")
    serializer_class = ShiftSerializer
    filterset_fields = ["is_active", "shop"]

    def perform_create(self, serializer):
        obj = serializer.save()
        _audit(action="SHIFT_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        _audit(action="SHIFT_SAVED", actor=self.request.user, entity=obj,
               request=self.request)


def _parse_date(value, name):
    d = parse_date(value) if value else None
    if value and d is None:
        raise ValueError(f"Invalid {name} date (expected YYYY-MM-DD).")
    return d


class _ReportBase(AdminAttendanceBase, APIView):
    def _filters(self, request):
        qp = request.query_params
        try:
            date_from = _parse_date(qp.get("date_from"), "date_from")
            date_to = _parse_date(qp.get("date_to"), "date_to")
        except ValueError as exc:
            return None, error_response(message=str(exc), code="INVALID_DATE")
        filters = {
            "date_from": date_from,
            "date_to": date_to,
            "shop_id": qp.get("shop_id") or None,
            "employee_id": qp.get("employee_id") or None,
            "include_test": str(qp.get("include_test", "")).lower()
            in {"1", "true", "yes"},
            "verified_only": str(qp.get("verified_only", "")).lower()
            in {"1", "true", "yes"},
        }
        return filters, None


@extend_schema(tags=["Attendance Admin"], summary="Daily attendance report")
class AttendanceDailyReportAPI(_ReportBase):
    """Daily summaries.

    TEST_MANUAL rows are excluded by default. `include_test=true` returns all
    rows; `verified_only=true` restricts to summaries without test events.
    """

    def get(self, request):
        filters, err = self._filters(request)
        if err:
            return err
        qs = AttendanceDailySummary.objects.select_related(
            "employee", "shop"
        ).order_by("-date", "employee__employee_code")
        if filters["verified_only"] or not filters["include_test"]:
            qs = qs.filter(contains_test_events=False)
        if filters["date_from"]:
            qs = qs.filter(date__gte=filters["date_from"])
        if filters["date_to"]:
            qs = qs.filter(date__lte=filters["date_to"])
        if filters["shop_id"]:
            qs = qs.filter(shop_id=filters["shop_id"])
        if filters["employee_id"]:
            qs = qs.filter(employee__employee_code=filters["employee_id"])
        data = AttendanceDailySummarySerializer(qs[:500], many=True).data
        return success_response(data={"results": data})


@extend_schema(tags=["Attendance Admin"], summary="Raw attendance events")
class AttendanceEventReportAPI(_ReportBase):
    def get(self, request):
        filters, err = self._filters(request)
        if err:
            return err
        qs = AttendanceEvent.objects.select_related(
            "employee", "shop", "device"
        ).order_by("-occurred_at", "-id")
        if not filters["include_test"]:
            qs = qs.filter(is_test_mode=False)
        if filters["date_from"]:
            qs = qs.filter(occurred_at__date__gte=filters["date_from"])
        if filters["date_to"]:
            qs = qs.filter(occurred_at__date__lte=filters["date_to"])
        if filters["shop_id"]:
            qs = qs.filter(shop_id=filters["shop_id"])
        if filters["employee_id"]:
            qs = qs.filter(employee__employee_code=filters["employee_id"])
        data = AdminAttendanceEventSerializer(qs[:1000], many=True).data
        return success_response(data={"results": data})


@extend_schema(tags=["Attendance Admin"], summary="Attendance audit log")
class AttendanceAuditLogListAPI(AdminAttendanceBase, APIView):
    def get(self, request):
        qs = AttendanceAuditLog.objects.select_related("actor", "device")
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        data = AttendanceAuditLogSerializer(qs[:500], many=True).data
        return success_response(data={"results": data})
