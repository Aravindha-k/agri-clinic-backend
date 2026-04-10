from django.urls import path
from .views import AuditLogListAPI

urlpatterns = [
    path("logs/", AuditLogListAPI.as_view(), name="audit-log-list"),
]
