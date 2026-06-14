from django.urls import path
from .views import (
    DashboardView,
    DashboardSummaryAPI,
    VisitTrendsAPI,
    EmployeePerformanceAPI,
    VillageHeatmapAPI,
)

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("summary/", DashboardSummaryAPI.as_view(), name="dashboard-summary"),
    path("visit-trends/", VisitTrendsAPI.as_view(), name="dashboard-visit-trends"),
    path(
        "employee-performance/",
        EmployeePerformanceAPI.as_view(),
        name="dashboard-emp-perf",
    ),
    path(
        "village-heatmap/",
        VillageHeatmapAPI.as_view(),
        name="dashboard-village-heatmap",
    ),
]
