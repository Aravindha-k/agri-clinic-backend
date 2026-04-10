from django.urls import path
from .views import SystemSettingsAPI, SystemConfigAPI

urlpatterns = [
    path("settings/", SystemSettingsAPI.as_view()),
    path("config/", SystemConfigAPI.as_view()),
]
