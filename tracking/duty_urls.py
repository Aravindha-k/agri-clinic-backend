from django.urls import path

from .duty_views import BulkLocationSyncAPI, DutyEndAPI, DutyStartAPI, LocationUpdateAPI
from .views import HeartbeatAPI

urlpatterns = [
    path("duty/start/", DutyStartAPI.as_view()),
    path("duty/end/", DutyEndAPI.as_view()),
    path("location/update/", LocationUpdateAPI.as_view()),
    path("location/bulk/", BulkLocationSyncAPI.as_view()),
    path("heartbeat/", HeartbeatAPI.as_view()),
]
