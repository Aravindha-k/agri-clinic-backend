from django.urls import path
from . import views
from .auth import MobileTokenObtainPairView, MobileTokenRefreshView, MobileMeView

urlpatterns = [
    path("auth/login/", MobileTokenObtainPairView.as_view(), name="mobile-login"),
    path("auth/refresh/", MobileTokenRefreshView.as_view(), name="mobile-refresh"),
    path("auth/me/", MobileMeView.as_view(), name="mobile-me"),
    path("dashboard/", views.MobileDashboardAPI.as_view(), name="mobile-dashboard"),
    path("work/start/", views.MobileWorkStartAPI.as_view(), name="mobile-work-start"),
    path("work/stop/", views.MobileWorkStopAPI.as_view(), name="mobile-work-stop"),
    path(
        "work/status/", views.MobileWorkStatusAPI.as_view(), name="mobile-work-status"
    ),
    path(
        "visits/stats/", views.MobileVisitStatsAPI.as_view(), name="mobile-visit-stats"
    ),
    path("tracking/", views.MobileTrackingAPI.as_view(), name="mobile-tracking"),
    path("reports/", views.MobileReportsAPI.as_view(), name="mobile-reports"),
    path("visits/", views.MobileVisitListCreateAPI.as_view(), name="mobile-visits"),
    # Other endpoints will be added here
]
