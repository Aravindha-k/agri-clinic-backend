from django.urls import path

from .admin_report_views import (
    AdminEmployeeDayReportAPI,
    AdminEmployeeDaySummaryAPI,
    AdminEmployeeVisitsByDateAPI,
)

urlpatterns = [
    path(
        "employee/<int:employee_id>/",
        AdminEmployeeVisitsByDateAPI.as_view(),
    ),
]

employee_urlpatterns = [
    path(
        "<int:employee_id>/day-summary/",
        AdminEmployeeDaySummaryAPI.as_view(),
    ),
    path(
        "<int:employee_id>/day-report/",
        AdminEmployeeDayReportAPI.as_view(),
    ),
]
