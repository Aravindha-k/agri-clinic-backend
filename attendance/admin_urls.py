from django.urls import include, path
from rest_framework.routers import DefaultRouter

from attendance.admin_views import (
    AttendanceAuditLogListAPI,
    AttendanceDailyReportAPI,
    AttendanceDeviceViewSet,
    AttendanceEmployeeViewSet,
    AttendanceEventReportAPI,
    EmployeeShopAssignmentViewSet,
    FaceEnrollmentViewSet,
    ShiftViewSet,
    ShopViewSet,
)

app_name = "attendance_admin"

router = DefaultRouter()
router.register(r"shops", ShopViewSet, basename="attendance-shop")
router.register(
    r"employees", AttendanceEmployeeViewSet, basename="attendance-employee"
)
router.register(r"devices", AttendanceDeviceViewSet, basename="attendance-device")
router.register(
    r"assignments",
    EmployeeShopAssignmentViewSet,
    basename="attendance-assignment",
)
router.register(r"shifts", ShiftViewSet, basename="attendance-shift")
router.register(
    r"face-enrollments",
    FaceEnrollmentViewSet,
    basename="attendance-face-enrollment",
)

urlpatterns = [
    path("reports/daily/", AttendanceDailyReportAPI.as_view(), name="report-daily"),
    path(
        "reports/events/", AttendanceEventReportAPI.as_view(), name="report-events"
    ),
    path("audit-logs/", AttendanceAuditLogListAPI.as_view(), name="audit-logs"),
    path("", include(router.urls)),
]
