from django.urls import path
from .views import (
    EmployeeVisitReportAPI,
    VillageVisitReportAPI,
    CropProblemReportAPI,
)
from .mobile_reports import DailyReportAPI, MonthlyReportAPI

urlpatterns = [
    path("employee-visits/", EmployeeVisitReportAPI.as_view()),
    path("village-visits/", VillageVisitReportAPI.as_view()),
    path("crop-problems/", CropProblemReportAPI.as_view()),
    path("daily/", DailyReportAPI.as_view(), name="daily-report"),
    path("monthly/", MonthlyReportAPI.as_view(), name="monthly-report"),
]
