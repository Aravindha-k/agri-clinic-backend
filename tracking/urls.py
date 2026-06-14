from django.urls import path
from .views import (
    StartWorkDayAPI,
    EndWorkDayAPI,
    HeartbeatAPI,
    PushLocationAPI,
    BulkPushLocationAPI,
    BulkLocationUploadAPI,
    AdminTrackingStatusAPI,
    AdminTrackingDashboardStatsAPI,
    AdminEmployeeRouteAPI,
    AdminEmployeesGeoJSONAPI,
    AdminEmployeeRouteGeoJSONAPI,
    AdminEmployeeLastLocationAPI,
    CurrentWorkdayAPI,
    WorkdayLocationsAPI,
    WorkdayHistoryAPI,
    AvailabilityEventsAPI,
    AdminEmployeeSummaryAPI,
    AdminEmployeeTrackingDiagnosticsAPI,
    AdminEmployeeActivityAPI,
    EmployeeStatsAPIView,
)
from .worklog_views import (
    WorkLogStartAPI,
    WorkLogEndAPI,
    WorkLogStatusAPI,
    WorkLogHistoryAPI,
)

urlpatterns = [
    # Employee APIs
    path("workday/start/", StartWorkDayAPI.as_view()),
    path("workday/end/", EndWorkDayAPI.as_view()),
    path("heartbeat/", HeartbeatAPI.as_view()),
    path("location/push/", PushLocationAPI.as_view()),
    path("locations/push/", PushLocationAPI.as_view()),
    path("location/bulk/", BulkLocationUploadAPI.as_view()),
    path("locations/bulk/", BulkLocationUploadAPI.as_view()),
    path("location/bulk-push/", BulkPushLocationAPI.as_view()),
    path("locations/bulk-push/", BulkPushLocationAPI.as_view()),
    # WorkLog endpoints
    path("work/start/", WorkLogStartAPI.as_view()),
    path("work/end/", WorkLogEndAPI.as_view()),
    path("work/status/", WorkLogStatusAPI.as_view()),
    path("work/history/", WorkLogHistoryAPI.as_view()),
    # Admin: dashboard
    path("admin/dashboard-stats/", AdminTrackingDashboardStatsAPI.as_view()),
    path("admin/status/", AdminTrackingStatusAPI.as_view()),
    # Admin: per-employee
    path("admin/employee/<int:user_id>/summary/", AdminEmployeeSummaryAPI.as_view()),
    path(
        "admin/employee/<int:user_id>/diagnostics/",
        AdminEmployeeTrackingDiagnosticsAPI.as_view(),
    ),
    path("admin/employee/<int:user_id>/route/", AdminEmployeeRouteAPI.as_view()),
    path("admin/employee/<int:user_id>/activity/", AdminEmployeeActivityAPI.as_view()),
    # Admin: GeoJSON
    path("admin/geo/employees/", AdminEmployeesGeoJSONAPI.as_view()),
    path("admin/geo/routes/<int:user_id>/", AdminEmployeeRouteGeoJSONAPI.as_view()),
    path(
        "admin/geo/last_location/<int:user_id>/",
        AdminEmployeeLastLocationAPI.as_view(),
    ),
    # Employee: workday & history
    path("workday/current/", CurrentWorkdayAPI.as_view()),
    path("workday/<int:workday_id>/locations/", WorkdayLocationsAPI.as_view()),
    path("workdays/history/", WorkdayHistoryAPI.as_view()),
    path("availability/events/", AvailabilityEventsAPI.as_view()),
    # Frontend aliases (backward compat)
    path("admin/employee-geo/", AdminEmployeesGeoJSONAPI.as_view()),
    path("admin/workday-history/", WorkdayHistoryAPI.as_view()),
    # Employee stats
    path("employee-stats/", EmployeeStatsAPIView.as_view(), name="employee-stats"),
]
