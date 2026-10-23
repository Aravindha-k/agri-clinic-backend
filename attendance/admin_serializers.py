"""Serializers for staff admin attendance APIs."""

from __future__ import annotations

from rest_framework import serializers

from attendance.models import (
    AttendanceAuditLog,
    AttendanceDailySummary,
    AttendanceDevice,
    AttendanceEmployee,
    AttendanceEvent,
    EmployeeShopAssignment,
    FaceEnrollment,
    Shift,
    Shop,
)


class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = [
            "id",
            "code",
            "name",
            "address",
            "area",
            "latitude",
            "longitude",
            "geofence_radius_m",
            "is_active",
            "archived_at",
            "archive_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["archived_at", "archive_reason", "created_at", "updated_at"]


class AttendanceDeviceSerializer(serializers.ModelSerializer):
    """Device representation — never exposes token material."""

    shop_code = serializers.CharField(source="shop.code", read_only=True)

    class Meta:
        model = AttendanceDevice
        fields = [
            "id",
            "shop",
            "shop_code",
            "device_uid",
            "name",
            "device_type",
            "token_prefix",
            "is_active",
            "registered_by",
            "last_seen_at",
            "created_at",
            "revoked_at",
        ]
        read_only_fields = [
            "device_uid",  # auto-generated 6-digit ID — never admin-entered
            "token_prefix",
            "registered_by",
            "last_seen_at",
            "created_at",
            "revoked_at",
        ]


class PairingCodeGenerateSerializer(serializers.Serializer):
    """Input for generate-pairing-code: pick a shop, optional label/type."""

    shop = serializers.PrimaryKeyRelatedField(queryset=Shop.objects.all())
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    device_type = serializers.ChoiceField(
        choices=AttendanceDevice.DEVICE_TYPE_CHOICES,
        default=AttendanceDevice.DEVICE_BIOMETRIC,
    )

    def validate_shop(self, shop: Shop):
        if not shop.is_active:
            raise serializers.ValidationError("Shop is not active.")
        return shop


class PairingCodeCreateSerializer(serializers.Serializer):
    """Input for POST devices/pairing-codes/: {"shop_id": 1}."""

    shop_id = serializers.PrimaryKeyRelatedField(
        queryset=Shop.objects.all(), source="shop"
    )
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    device_type = serializers.ChoiceField(
        choices=AttendanceDevice.DEVICE_TYPE_CHOICES,
        default=AttendanceDevice.DEVICE_KIOSK,
    )

    def validate_shop_id(self, shop: Shop):
        if not shop.is_active:
            raise serializers.ValidationError("Shop is not active.")
        return shop


class DeviceRegisterResponseSerializer(serializers.Serializer):
    device = AttendanceDeviceSerializer()
    token = serializers.CharField(help_text="Shown once; store securely.")


class AttendanceEmployeeSerializer(serializers.ModelSerializer):
    """Admin CRUD for attendance-only employees (no login credentials)."""

    linked_employee_id = serializers.CharField(
        source="linked_profile.employee_id", read_only=True, default=None
    )
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, default=None
    )
    updated_by_username = serializers.CharField(
        source="updated_by.username", read_only=True, default=None
    )
    enrollment_status = serializers.SerializerMethodField()

    def get_enrollment_status(self, obj):
        latest = getattr(obj, "_latest_enrollment_status", None)
        if latest is not None:
            return latest
        row = (
            obj.face_enrollments.order_by("-created_at")
            .values_list("status", flat=True)
            .first()
        )
        return row or "NONE"

    class Meta:
        model = AttendanceEmployee
        fields = [
            "id",
            "employee_code",
            "full_name",
            "phone",
            "is_active",
            "linked_profile",
            "linked_employee_id",
            "enrollment_status",
            "created_by_username",
            "updated_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "is_active",
            "enrollment_status",
            "created_by_username",
            "updated_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_employee_code(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("employee_code is required.")
        return value


class FaceEnrollmentSerializer(serializers.ModelSerializer):
    """Enrollment metadata — never exposes images, embeddings or templates."""

    employee_ref = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    shop_code = serializers.CharField(source="shop.code", read_only=True)
    device_uid = serializers.CharField(
        source="device.device_uid", read_only=True, default=None
    )
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, default=None
    )

    class Meta:
        model = FaceEnrollment
        fields = [
            "id",
            "employee",
            "employee_ref",
            "employee_name",
            "shop",
            "shop_code",
            "device",
            "device_uid",
            "status",
            "consent_recorded",
            "consent_at",
            "sample_count",
            "enrolled_at",
            "created_by_username",
            "revoked_at",
            "revoke_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "consent_at",
            "sample_count",
            "enrolled_at",
            "created_by_username",
            "revoked_at",
            "revoke_reason",
            "created_at",
            "updated_at",
        ]


class FaceEnrollmentAuthorizeSerializer(serializers.Serializer):
    """Input for POST face-enrollments/ (admin authorizes an enrollment)."""

    employee = serializers.PrimaryKeyRelatedField(
        queryset=AttendanceEmployee.objects.filter(is_active=True)
    )
    shop = serializers.PrimaryKeyRelatedField(queryset=Shop.objects.all())
    device = serializers.PrimaryKeyRelatedField(
        queryset=AttendanceDevice.objects.filter(is_active=True)
    )
    consent_recorded = serializers.BooleanField(default=False)

    def validate_shop(self, shop: Shop):
        if not shop.is_active or shop.archived_at is not None:
            raise serializers.ValidationError("Shop is not active.")
        return shop

    def validate_device(self, device: AttendanceDevice):
        if device.revoked_at is not None:
            raise serializers.ValidationError("Device is revoked.")
        return device

    def validate(self, attrs):
        if attrs["device"].shop_id != attrs["shop"].id:
            raise serializers.ValidationError(
                "Device does not belong to the selected shop."
            )
        if not attrs["consent_recorded"]:
            raise serializers.ValidationError(
                "Employee consent must be recorded before authorizing enrollment."
            )
        if not EmployeeShopAssignment.objects.filter(
            employee=attrs["employee"], shop=attrs["shop"], is_active=True
        ).exists():
            raise serializers.ValidationError(
                "Employee is not assigned to the selected shop."
            )
        return attrs


class EmployeeShopAssignmentSerializer(serializers.ModelSerializer):
    employee_ref = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    shop_code = serializers.CharField(source="shop.code", read_only=True)
    shift_name = serializers.CharField(
        source="shift.name", read_only=True, default=None
    )

    class Meta:
        model = EmployeeShopAssignment
        fields = [
            "id",
            "employee",
            "employee_ref",
            "employee_name",
            "shop",
            "shop_code",
            "shift",
            "shift_name",
            "is_active",
            "valid_from",
            "valid_to",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_employee(self, value: AttendanceEmployee):
        if not value.is_active:
            raise serializers.ValidationError("Employee is not active.")
        return value


class ShiftSerializer(serializers.ModelSerializer):
    crosses_midnight = serializers.BooleanField(read_only=True)

    class Meta:
        model = Shift
        fields = [
            "id",
            "shop",
            "name",
            "start_time",
            "end_time",
            "grace_minutes",
            "is_active",
            "crosses_midnight",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class AttendanceDailySummarySerializer(serializers.ModelSerializer):
    employee_ref = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    class Meta:
        model = AttendanceDailySummary
        fields = [
            "id",
            "employee_ref",
            "employee_name",
            "shop_code",
            "date",
            "first_check_in",
            "last_check_out",
            "worked_seconds",
            "status",
            "has_open_session",
            "contains_test_events",
        ]


class AdminAttendanceEventSerializer(serializers.ModelSerializer):
    employee_ref = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    shop_code = serializers.CharField(source="shop.code", read_only=True)
    device_uid = serializers.CharField(
        source="device.device_uid", read_only=True, default=None
    )

    class Meta:
        model = AttendanceEvent
        fields = [
            "id",
            "employee_ref",
            "shop_code",
            "device_uid",
            "event_type",
            "occurred_at",
            "verification_method",
            "is_test_mode",
            "latitude",
            "longitude",
            "recorded_by",
            "notes",
        ]


class AttendanceAuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(
        source="actor.username", read_only=True, default=None
    )
    device_uid = serializers.CharField(
        source="device.device_uid", read_only=True, default=None
    )

    class Meta:
        model = AttendanceAuditLog
        fields = [
            "id",
            "action",
            "actor_username",
            "device_uid",
            "entity_type",
            "entity_id",
            "metadata",
            "ip_address",
            "created_at",
        ]
