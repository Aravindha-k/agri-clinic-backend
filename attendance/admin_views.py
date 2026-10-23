"""Staff admin APIs: shops, devices, assignments, shifts, reports, audit log."""

from __future__ import annotations

import logging

from django.db import transaction
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
    FaceEnrollmentAuthorizeSerializer,
    FaceEnrollmentSerializer,
    PairingCodeCreateSerializer,
    PairingCodeGenerateSerializer,
    ShiftSerializer,
    ShopSerializer,
)
from attendance import devices
from attendance.devices import issue_device, revoke_device, rotate_device_token
from attendance.models import (
    AttendanceAuditLog,
    AttendanceDailySummary,
    AttendanceDevice,
    AttendanceEmployee,
    AttendanceEvent,
    DevicePairingCode,
    EmployeeShopAssignment,
    FaceEnrollment,
    Shift,
    Shop,
)
from attendance.services import _audit
from utils.permissions import IsStaffAdmin
from utils.response import created_response, error_response, success_response

logger = logging.getLogger(__name__)


class AdminAttendanceBase:
    permission_classes = [IsStaffAdmin]


def _shop_dependency_summary(shop: Shop) -> dict:
    """Counts of everything that protects a shop from hard deletion."""
    return {
        "devices_total": shop.attendance_devices.count(),
        "devices_active": shop.attendance_devices.filter(
            is_active=True
        ).count(),
        "employee_assignments_total": shop.employee_assignments.count(),
        "employee_assignments_active": shop.employee_assignments.filter(
            is_active=True
        ).count(),
        "shifts": shop.shifts.count(),
        "attendance_events": shop.attendance_events.count(),
        "daily_summaries": shop.attendance_daily_summaries.count(),
        "audit_records": AttendanceAuditLog.objects.filter(
            entity_type="Shop", entity_id=str(shop.pk)
        ).count(),
    }


def _shop_has_protected_history(summary: dict) -> bool:
    return bool(
        summary["devices_total"]
        or summary["employee_assignments_total"]
        or summary["shifts"]
        or summary["attendance_events"]
        or summary["daily_summaries"]
    )


class ShopViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    """Shop CRUD. Deletion is dependency-aware: archive, never cascade."""

    serializer_class = ShopSerializer
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        qs = Shop.objects.all()
        if str(self.request.query_params.get("include_archived", "")).lower() not in {
            "1", "true", "yes",
        }:
            qs = qs.filter(archived_at__isnull=True)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        _audit(action="SHOP_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        _audit(action="SHOP_SAVED", actor=self.request.user, entity=obj,
               request=self.request)

    @action(detail=True, methods=["get"], url_path="dependency-summary")
    def dependency_summary(self, request, pk=None):
        shop = self.get_object()
        summary = _shop_dependency_summary(shop)
        return success_response(
            data={
                "shop": ShopSerializer(shop).data,
                "dependencies": summary,
                "archived": shop.archived_at is not None,
                "can_archive": shop.archived_at is None,
                "can_permanently_delete": not _shop_has_protected_history(summary),
            }
        )

    def destroy(self, request, *args, **kwargs):
        """Archive shops with history; hard-delete only empty disposable shops.

        `?permanent=true` is required for a hard delete and is refused when
        any protected dependency exists — attendance history is never lost.
        """
        from django.utils import timezone

        shop = self.get_object()
        summary = _shop_dependency_summary(shop)
        wants_permanent = str(
            request.query_params.get("permanent", "")
        ).lower() in {"1", "true", "yes"}
        reason = str(request.data.get("reason") or "")[:160]

        if wants_permanent:
            if _shop_has_protected_history(summary):
                return error_response(
                    message=(
                        "Shop has devices, assignments, shifts or attendance "
                        "history — it can only be archived."
                    ),
                    code="SHOP_DELETE_BLOCKED",
                    status_code=409,
                )
            shop_pk, shop_code = shop.pk, shop.code
            shop.delete()
            _audit(
                action="SHOP_DELETED",
                actor=request.user,
                metadata={
                    "shop_id": shop_pk,
                    "shop_code": shop_code,
                    "reason": reason,
                },
                request=request,
            )
            return success_response(
                data={"dependencies": summary, "permanently_deleted": True},
                message="Shop permanently deleted (no protected history).",
            )

        if shop.archived_at is not None:
            return error_response(
                message="Shop is already archived.",
                code="SHOP_ALREADY_ARCHIVED",
                status_code=409,
            )
        shop.archived_at = timezone.now()
        shop.archived_by = request.user
        shop.archive_reason = reason
        shop.is_active = False
        shop.save(
            update_fields=[
                "archived_at", "archived_by", "archive_reason",
                "is_active", "updated_at",
            ]
        )
        _audit(
            action="SHOP_ARCHIVED",
            actor=request.user,
            entity=shop,
            metadata={"reason": reason, "dependencies": summary},
            request=request,
        )
        return success_response(
            data={
                "shop": ShopSerializer(shop).data,
                "dependencies": summary,
                "archived": True,
            },
            message="Shop archived. Attendance history is preserved.",
        )


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

    def _issue_pairing_code(self, request, *, shop, name, device_type):
        try:
            issued = devices.generate_pairing_code(
                shop=shop,
                name=name or "",
                device_type=device_type,
                created_by=request.user,
            )
        except devices.PairingError as exc:
            return None, error_response(
                message=str(exc), code=exc.code, status_code=503
            )
        _audit(
            action="PAIRING_CODE_ISSUED", actor=request.user,
            device=issued.device, entity=issued.device,
            metadata={
                "code_prefix": issued.plaintext_code[:2],
                "shop_code": shop.code,
            },
            request=request,
        )
        return issued, None

    @action(detail=False, methods=["post"], url_path="pairing-codes")
    def pairing_codes(self, request):
        """Generate a 6-digit setup code for a shop (Android kiosk pairing).

        Returns the plaintext code ONCE, over this authenticated HTTPS call.
        """
        serializer = PairingCodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued, err = self._issue_pairing_code(
            request,
            shop=serializer.validated_data["shop"],
            name=serializer.validated_data.get("name") or "",
            device_type=serializer.validated_data.get(
                "device_type", AttendanceDevice.DEVICE_KIOSK
            ),
        )
        if err:
            return err
        ttl_seconds = DevicePairingCode.TTL_MINUTES * 60
        return created_response(
            data={
                "pairing_code": issued.plaintext_code,
                "expires_in_seconds": ttl_seconds,
                "expires_at": issued.expires_at,
                "device_uid": issued.device.device_uid,
                "shop_id": issued.device.shop_id,
                "shop_code": issued.device.shop.code,
            },
            message="Pairing code generated. It expires shortly and works once.",
        )

    @action(detail=False, methods=["post"], url_path="generate-pairing-code")
    def generate_pairing_code(self, request):
        """Create an inactive device + one-time 6-digit setup code.

        Returns the plaintext code ONCE. The device token is issued later,
        directly to the kiosk at redemption — never via the admin panel.
        """
        serializer = PairingCodeGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued, err = self._issue_pairing_code(
            request,
            shop=serializer.validated_data["shop"],
            name=serializer.validated_data.get("name") or "",
            device_type=serializer.validated_data.get(
                "device_type", AttendanceDevice.DEVICE_BIOMETRIC
            ),
        )
        if err:
            return err
        return created_response(
            data={
                "device": AttendanceDeviceSerializer(issued.device).data,
                "code": issued.plaintext_code,
                "expires_at": issued.expires_at,
            },
            message="Pairing code generated. It expires shortly and works once.",
        )

    def destroy(self, request, *args, **kwargs):
        """Revoke devices with history; hard-delete only disposable ones.

        Attendance events keep a FK reference to the device (PROTECT), so a
        device that ever submitted events can only be revoked — its identity
        and history are preserved. A device with zero events and no live
        enrollments is a disposable test device and may be hard-deleted.
        """
        device = self.get_object()
        events = device.attendance_events.count()
        live_enrollments = device.face_enrollments.filter(
            status__in=[FaceEnrollment.STATUS_PENDING, FaceEnrollment.STATUS_ACTIVE]
        ).count()
        if events or live_enrollments:
            if device.revoked_at is None:
                revoke_device(device)
                _audit(
                    action="DEVICE_REVOKED", actor=request.user, device=device,
                    entity=device,
                    metadata={
                        "reason": "admin delete (has history — revoked instead)"
                    },
                    request=request,
                )
            return success_response(
                data={
                    "device_uid": device.device_uid,
                    "attendance_events": events,
                    "live_enrollments": live_enrollments,
                    "revoked": True,
                    "permanently_deleted": False,
                },
                message=(
                    "Device has attendance history or enrollments — "
                    "it was revoked instead of deleted."
                ),
            )
        uid, shop_id = device.device_uid, device.shop_id
        device.delete()
        _audit(
            action="DEVICE_DELETED",
            actor=request.user,
            metadata={
                "device_uid": uid,
                "shop_id": shop_id,
                "reason": str(request.data.get("reason") or "")[:160],
            },
            request=request,
        )
        return success_response(
            data={"device_uid": uid, "permanently_deleted": True},
            message="Device permanently deleted (no protected history).",
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
    def restore(self, request, pk=None):
        """Explicit admin re-activation of a revoked device."""
        device = self.get_object()
        if device.revoked_at is None:
            return error_response(
                message="Device is not revoked.",
                code="DEVICE_NOT_REVOKED",
                status_code=409,
            )
        device.revoked_at = None
        device.is_active = True
        device.save(update_fields=["revoked_at", "is_active"])
        _audit(action="DEVICE_UPDATED", actor=request.user, device=device,
               entity=device, metadata={"restored": True},
               request=request)
        return success_response(
            data={"device": AttendanceDeviceSerializer(device).data},
            message="Device restored.",
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


class FaceEnrollmentViewSet(AdminAttendanceBase, viewsets.ModelViewSet):
    """Admin face-enrollment authorization lifecycle.

    Only metadata is managed here — no images, embeddings or templates
    ever pass through this API.
    """

    serializer_class = FaceEnrollmentSerializer
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["employee", "shop", "device", "status"]
    search_fields = ["employee__employee_code", "employee__full_name"]

    def get_queryset(self):
        return FaceEnrollment.objects.select_related(
            "employee", "shop", "device", "created_by"
        )

    def create(self, request, *args, **kwargs):
        from django.utils import timezone

        ser = FaceEnrollmentAuthorizeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        with transaction.atomic():
            # Replace any live enrollment for this employee+device.
            previous = list(
                FaceEnrollment.objects.select_for_update().filter(
                    employee=data["employee"],
                    device=data["device"],
                    status__in=[
                        FaceEnrollment.STATUS_PENDING,
                        FaceEnrollment.STATUS_ACTIVE,
                    ],
                )
            )
            for old in previous:
                old.status = FaceEnrollment.STATUS_REPLACED
                old.revoked_by = request.user
                old.revoked_at = timezone.now()
                old.revoke_reason = "replaced by re-authorization"
                old.save(
                    update_fields=[
                        "status", "revoked_by", "revoked_at",
                        "revoke_reason", "updated_at",
                    ]
                )
            enrollment = FaceEnrollment.objects.create(
                employee=data["employee"],
                shop=data["shop"],
                device=data["device"],
                status=FaceEnrollment.STATUS_PENDING,
                consent_recorded=True,
                consent_at=timezone.now(),
                created_by=request.user,
            )
            for old in previous:
                old.revoke_reason = f"replaced by enrollment #{enrollment.pk}"
                old.save(update_fields=["revoke_reason", "updated_at"])
                _audit(
                    action="ENROLLMENT_REPLACED",
                    actor=request.user,
                    entity=old,
                    metadata={"replaced_by": enrollment.pk},
                    request=request,
                )
            _audit(
                action="ENROLLMENT_AUTHORIZED",
                actor=request.user,
                entity=enrollment,
                metadata={
                    "employee_code": data["employee"].employee_code,
                    "shop": data["shop"].code,
                    "device_uid": data["device"].device_uid,
                },
                request=request,
            )
        return success_response(
            data=FaceEnrollmentSerializer(enrollment).data,
            message="Enrollment authorized.",
            status_code=201,
        )

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        from django.utils import timezone

        enrollment = self.get_object()
        if enrollment.status not in (
            FaceEnrollment.STATUS_PENDING,
            FaceEnrollment.STATUS_ACTIVE,
        ):
            return error_response(
                message="Enrollment is already closed.",
                code="ENROLLMENT_ALREADY_CLOSED",
                status_code=409,
            )
        enrollment.status = FaceEnrollment.STATUS_REVOKED
        enrollment.revoked_by = request.user
        enrollment.revoked_at = timezone.now()
        enrollment.revoke_reason = str(request.data.get("reason") or "")[:160]
        enrollment.save(
            update_fields=[
                "status", "revoked_by", "revoked_at",
                "revoke_reason", "updated_at",
            ]
        )
        _audit(
            action="ENROLLMENT_REVOKED",
            actor=request.user,
            entity=enrollment,
            metadata={"reason": enrollment.revoke_reason},
            request=request,
        )
        return success_response(
            data=FaceEnrollmentSerializer(enrollment).data,
            message="Enrollment revoked — device must no longer authorize "
                    "this employee's face.",
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
