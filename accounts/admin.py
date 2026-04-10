from django.contrib import admin
from .models import EmployeeProfile


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = (
        "employee_id",
        "username",
        "phone",
        "is_active_employee",
        "user_is_active",
    )
    search_fields = ("employee_id", "user__username", "phone")
    list_filter = ("is_active_employee",)

    def username(self, obj):
        return obj.user.username

    def user_is_active(self, obj):
        return obj.user.is_active

    user_is_active.boolean = True
    user_is_active.short_description = "User Active"
