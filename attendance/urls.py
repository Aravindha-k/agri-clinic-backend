from django.urls import path

from attendance.views import (
    AttendanceCheckInAPI,
    AttendanceCheckOutAPI,
    AttendanceEmployeeListAPI,
    AttendanceStatusAPI,
)

app_name = "attendance"

urlpatterns = [
    path("employees/", AttendanceEmployeeListAPI.as_view(), name="employees"),
    path("check-in/", AttendanceCheckInAPI.as_view(), name="check-in"),
    path("check-out/", AttendanceCheckOutAPI.as_view(), name="check-out"),
    path("status/", AttendanceStatusAPI.as_view(), name="status"),
]
