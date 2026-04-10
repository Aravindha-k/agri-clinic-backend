from django.contrib import admin
from .models import WorkDay, LocationLog, AvailabilityEvent


@admin.register(WorkDay)
class WorkDayAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "date",
        "start_time",
        "end_time",
        "is_active",
        "last_heartbeat",
    )
    list_filter = ("is_active", "date")
    search_fields = ("user__username",)


@admin.register(LocationLog)
class LocationLogAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "workday",
        "latitude",
        "longitude",
        "accuracy",
        "recorded_at",
    )
    list_filter = ("recorded_at",)
    search_fields = ("user__username",)


@admin.register(AvailabilityEvent)
class AvailabilityEventAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "workday",
        "event_type",
        "start_time",
        "end_time",
    )
    list_filter = ("event_type",)
    search_fields = ("user__username",)
