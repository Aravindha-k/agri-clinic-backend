from django.urls import path
from .views import NotificationListAPI

urlpatterns = [
    path("list/", NotificationListAPI.as_view()),
]
