from django.urls import path

from tracking.views import (
    StartDayAPI,
    EndDayAPI,
    PushLocationAPI,
    HeartbeatAPI,
    AdminTrackingStatusAPI,
    AdminEmployeeLocationAPI,
)

urlpatterns = [
    # ✅ Employee APIs
    path("start-day/", StartDayAPI.as_view()),
    path("end-day/", EndDayAPI.as_view()),
    path("heartbeat/", HeartbeatAPI.as_view()),
    path("push-location/", PushLocationAPI.as_view()),
    # ✅ Admin APIs
    path("admin-status/", AdminTrackingStatusAPI.as_view()),
    path("admin/locations/<int:user_id>/", AdminEmployeeLocationAPI.as_view()),
]
