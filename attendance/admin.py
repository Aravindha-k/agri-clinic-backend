from django.contrib import admin

from attendance.models import (
    AttendanceAuditLog,
    AttendanceDailySummary,
    AttendanceDevice,
    AttendanceEvent,
    EmployeeShopAssignment,
    Shift,
    Shop,
)


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(AttendanceDevice)
class AttendanceDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "device_uid",
        "name",
        "shop",
        "device_type",
        "is_active",
        "last_seen_at",
    )
    list_filter = ("is_active", "device_type", "shop")
    search_fields = ("device_uid", "name")
    readonly_fields = ("token_hash", "token_prefix", "last_seen_at", "revoked_at")


@admin.register(EmployeeShopAssignment)
class EmployeeShopAssignmentAdmin(admin.ModelAdmin):
    list_display = ("employee", "shop", "is_active", "valid_from", "valid_to")
    list_filter = ("is_active", "shop")
    search_fields = ("employee__employee_id", "shop__code")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "shop", "start_time", "end_time", "is_active")
    list_filter = ("is_active", "shop")


@admin.register(AttendanceEvent)
class AttendanceEventAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "shop",
        "event_type",
        "occurred_at",
        "verification_method",
        "is_test_mode",
    )
    list_filter = ("event_type", "verification_method", "is_test_mode", "shop")
    search_fields = ("employee__employee_id", "client_event_id")
    readonly_fields = ("created_at",)


@admin.register(AttendanceDailySummary)
class AttendanceDailySummaryAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "shop",
        "date",
        "status",
        "worked_seconds",
        "has_open_session",
        "contains_test_events",
    )
    list_filter = ("status", "contains_test_events", "shop", "date")


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "device", "entity_type", "entity_id", "created_at")
    list_filter = ("action", "created_at")
    readonly_fields = ("metadata", "ip_address", "created_at")
