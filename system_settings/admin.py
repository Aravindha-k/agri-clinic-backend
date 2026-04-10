from django.contrib import admin
from .models import SystemSetting, SystemConfig

admin.site.register(SystemSetting)


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = (
        "heartbeat_timeout_minutes",
        "gps_accuracy_limit",
        "gps_jump_limit_km",
        "tracking_stale_minutes",
        "updated_at",
    )

    def has_add_permission(self, request):
        # Only allow one row
        return not SystemConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
