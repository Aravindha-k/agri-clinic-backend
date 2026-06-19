from django.urls import path
from .duty_views import BulkLocationSyncAPI, DutyEndAPI, DutyStartAPI, LocationUpdateAPI
from .admin_duty_views import (
    AdminEmployeeRouteByDateAPI,
    AdminEmployeeTodayRouteAPI,
    AdminTrackingLiveAPI,
)
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
    AdminEmployeeDailySummaryAPI,
    EmployeeStatsAPIView,
)
from .worklog_views import (
    WorkLogStartAPI,
    WorkLogEndAPI,
    WorkLogStatusAPI,
    WorkLogHistoryAPI,
)

urlpatterns = [
    # Duty tracking (also under /api/v1/tracking/)
    path("duty/start/", DutyStartAPI.as_view()),
    path("duty/end/", DutyEndAPI.as_view()),
    path("location/update/", LocationUpdateAPI.as_view()),
    path("location/bulk/", BulkLocationSyncAPI.as_view()),
    path("locations/bulk/", BulkLocationUploadAPI.as_view()),
    path("location/bulk-push/", BulkPushLocationAPI.as_view()),
    path("locations/bulk-push/", BulkPushLocationAPI.as_view()),
    # Employee APIs (legacy workday)
    path("workday/start/", StartWorkDayAPI.as_view()),
    path("workday/end/", EndWorkDayAPI.as_view()),
    path("heartbeat/", HeartbeatAPI.as_view()),
    path("location/push/", PushLocationAPI.as_view()),
    path("locations/push/", PushLocationAPI.as_view()),
    # WorkLog endpoints
    path("work/start/", WorkLogStartAPI.as_view()),
    path("work/end/", WorkLogEndAPI.as_view()),
    path("work/status/", WorkLogStatusAPI.as_view()),
    path("work/history/", WorkLogHistoryAPI.as_view()),
    # Admin: dashboard
    path("admin/dashboard-stats/", AdminTrackingDashboardStatsAPI.as_view()),
    path("admin/status/", AdminTrackingStatusAPI.as_view()),
    path("admin/live/", AdminTrackingLiveAPI.as_view()),
    path(
        "admin/employee/<int:user_id>/today-route/",
        AdminEmployeeTodayRouteAPI.as_view(),
    ),
    path(
        "admin/employee/<int:user_id>/route-by-date/",
        AdminEmployeeRouteByDateAPI.as_view(),
    ),
    # Admin: per-employee
    path("admin/employee/<int:user_id>/summary/", AdminEmployeeSummaryAPI.as_view()),
    path(
        "admin/employee/<int:user_id>/diagnostics/",
        AdminEmployeeTrackingDiagnosticsAPI.as_view(),
    ),
    path("admin/employee/<int:user_id>/route/", AdminEmployeeRouteAPI.as_view()),
    path(
        "admin/employee/<int:user_id>/daily-summary/",
        AdminEmployeeDailySummaryAPI.as_view(),
    ),
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
