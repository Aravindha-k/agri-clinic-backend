from django.urls import path

from attendance.views import (
    AttendanceCheckInAPI,
    AttendanceCheckOutAPI,
    AttendanceEmployeeListAPI,
    AttendanceStatusAPI,
    DevicePairingAPI,
    FaceEnrollmentCompleteAPI,
    FaceEnrollmentListAPI,
)

app_name = "attendance"

urlpatterns = [
    path("employees/", AttendanceEmployeeListAPI.as_view(), name="employees"),
    path("check-in/", AttendanceCheckInAPI.as_view(), name="check-in"),
    path("check-out/", AttendanceCheckOutAPI.as_view(), name="check-out"),
    path("status/", AttendanceStatusAPI.as_view(), name="status"),
    path(
        "enrollments/",
        FaceEnrollmentListAPI.as_view(),
        name="enrollments",
    ),
    path(
        "enrollments/<int:enrollment_id>/complete/",
        FaceEnrollmentCompleteAPI.as_view(),
        name="enrollment-complete",
    ),
    path("devices/pair/", DevicePairingAPI.as_view(), name="pair"),
    path("devices/pair/", DevicePairingAPI.as_view(), name="devices-pair"),
]
