from django.urls import path

from .admin_duty_views import (
    AdminEmployeeEndDutyAPI,
    AdminEmployeeRouteByDateAPI,
    AdminEmployeeTodayRouteAPI,
    AdminTrackingLiveAPI,
)

urlpatterns = [
    path("live/", AdminTrackingLiveAPI.as_view()),
    path(
        "employee/<int:user_id>/today-route/",
        AdminEmployeeTodayRouteAPI.as_view(),
    ),
    path(
        "employee/<int:user_id>/route/",
        AdminEmployeeRouteByDateAPI.as_view(),
    ),
    path(
        "employee/<int:user_id>/end-duty/",
        AdminEmployeeEndDutyAPI.as_view(),
    ),
]
