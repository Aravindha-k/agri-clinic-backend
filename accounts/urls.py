from django.urls import path
from .views import (
    CreateEmployeeAPI,
    AdminResetPasswordAPI,
    EmployeeListAPI,
    ToggleEmployeeStatusAPI,
    AdminEmployeeUpdateDeleteAPI,
    CreateAdminAPI,
    LogoutAPI,
    AdminEmployeeManagementAPI,
    AdminEmployeeDetailAPI,
    AdminEmployeeToggleStatusAPI,
    ChangePasswordAPI,
    AdminSecurityMonitoringAPI,
)
from .profile_api import EmployeeProfileAPI
from .profile_photos import EmployeeSelfPhotoAPI

app_name = "accounts"

urlpatterns = [
    # Auth / Context
    path("create-admin/", CreateAdminAPI.as_view()),
    # Main employees list endpoint (now root)
    path("", EmployeeListAPI.as_view(), name="employee-list"),
    path("create/", CreateEmployeeAPI.as_view(), name="employee-create"),
    path(
        "<str:employee_id>/toggle/",
        ToggleEmployeeStatusAPI.as_view(),
        name="employee-toggle",
    ),
    path(
        "<int:employee_id>/",
        AdminEmployeeUpdateDeleteAPI.as_view(),
        name="employee-update-delete",
    ),
    # Admin – Employee Management (production)
    path(
        "admin/employees/",
        AdminEmployeeManagementAPI.as_view(),
        name="admin-employee-list-create",
    ),
    path(
        "admin/employees/<int:pk>/",
        AdminEmployeeDetailAPI.as_view(),
        name="admin-employee-detail",
    ),
    path(
        "admin/employees/<int:pk>/toggle-status/",
        AdminEmployeeToggleStatusAPI.as_view(),
        name="admin-employee-toggle-status",
    ),
    # Admin – Security
    path(
        "admin/reset-password/",
        AdminResetPasswordAPI.as_view(),
        name="admin-reset-password",
    ),
    path(
        "change-password/",
        ChangePasswordAPI.as_view(),
        name="change-password",
    ),
    path(
        "admin/security/",
        AdminSecurityMonitoringAPI.as_view(),
        name="admin-security-monitoring",
    ),
    path("logout/", LogoutAPI.as_view(), name="logout"),
    # Profile photo + me (specific paths before me/)
    path("me/photo/", EmployeeSelfPhotoAPI.as_view(), name="employee-self-photo"),
    path("me/", EmployeeProfileAPI.as_view(), name="employee-profile-me"),
]
