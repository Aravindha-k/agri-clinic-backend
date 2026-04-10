from django.urls import path
from .views import (
    NotificationListAPI,
    NotificationMarkReadAPI,
    NotificationMarkAllReadAPI,
    NotificationUnreadCountAPI,
)

urlpatterns = [
    path("", NotificationListAPI.as_view(), name="notification-list"),
    path("list/", NotificationListAPI.as_view(), name="notification-list-alt"),
    path(
        "unread-count/",
        NotificationUnreadCountAPI.as_view(),
        name="notification-unread-count",
    ),
    path(
        "mark-all-read/",
        NotificationMarkAllReadAPI.as_view(),
        name="notification-mark-all-read",
    ),
    path(
        "<int:pk>/read/",
        NotificationMarkReadAPI.as_view(),
        name="notification-mark-read",
    ),
]
