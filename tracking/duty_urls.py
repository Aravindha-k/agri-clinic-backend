from django.urls import path

from .duty_views import (
    BulkLocationSyncAPI,
    DutyCurrentAPI,
    DutyCurrentMapAPI,
    DutyDayMapAPI,
    DutyEndAPI,
    DutyStartAPI,
    LocationUpdateAPI,
)
from .views import HeartbeatAPI

urlpatterns = [
    path("duty/start/", DutyStartAPI.as_view()),
    path("duty/end/", DutyEndAPI.as_view()),
    path("duty/current/", DutyCurrentAPI.as_view()),
    path("duty/current/map/", DutyCurrentMapAPI.as_view()),
    path("duty/<int:duty_session_id>/map/", DutyDayMapAPI.as_view()),
    path("location/update/", LocationUpdateAPI.as_view()),
    path("location/bulk/", BulkLocationSyncAPI.as_view()),
    path("heartbeat/", HeartbeatAPI.as_view()),
]
