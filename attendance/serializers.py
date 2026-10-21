"""Serializers for device-facing attendance endpoints."""

from __future__ import annotations

from rest_framework import serializers

from accounts.models import EmployeeProfile
from attendance.models import AttendanceEvent


class SelectableEmployeeSerializer(serializers.ModelSerializer):
    """Employee rows for the test-mode selection screen."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeProfile
        fields = ["id", "employee_id", "name", "role"]

    def get_name(self, obj) -> str:
        full = obj.user.get_full_name()
        return full or obj.user.username


class EventWriteSerializer(serializers.Serializer):
    """Check-in / check-out payload.

    Shop is derived from the authenticated device; verification_method is
    never accepted from the client.
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
    employee_id = serializers.CharField(source="employee.employee_id", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    class Meta:
        model = AttendanceEvent
        fields = [
            "id",
            "employee_id",
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
