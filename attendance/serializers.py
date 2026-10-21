"""Serializers for device-facing attendance endpoints."""

from __future__ import annotations

from rest_framework import serializers

from attendance.models import AttendanceEmployee, AttendanceEvent


class SelectableEmployeeSerializer(serializers.ModelSerializer):
    """Attendance employees for the test-mode selection screen."""

    name = serializers.CharField(source="full_name", read_only=True)
    employee_id = serializers.CharField(source="employee_code", read_only=True)

    class Meta:
        model = AttendanceEmployee
        fields = ["id", "employee_id", "name", "phone"]


class EventWriteSerializer(serializers.Serializer):
    """Check-in / check-out payload.

    Shop is derived from the authenticated device; verification_method is
    never accepted from the client. `employee_id` is the AttendanceEmployee
    primary key (not a code and not a Field Officer user id).
    """

    employee_id = serializers.IntegerField(min_value=1)
    client_event_id = serializers.CharField(
        max_length=64, required=False, allow_blank=True
    )
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )


class AttendanceEventSerializer(serializers.ModelSerializer):
    employee_id = serializers.CharField(source="employee.employee_code", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    class Meta:
        model = AttendanceEvent
        fields = [
            "id",
            "employee_id",
            "employee_name",
            "shop_code",
            "event_type",
            "occurred_at",
            "verification_method",
            "is_test_mode",
            "client_event_id",
        ]
        read_only_fields = fields


class AttendanceStatusSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(min_value=1)
