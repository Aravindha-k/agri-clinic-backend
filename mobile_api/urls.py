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
    path(
        "visits/<int:pk>/",
        views.MobileVisitDetailAPI.as_view(),
        name="mobile-visit-detail",
    ),
    path(
        "visits/<int:pk>/media/",
        views.MobileVisitMediaUploadAPI.as_view(),
        name="mobile-visit-media",
    ),
    path("farmers/", views.MobileFarmerListAPI.as_view(), name="mobile-farmers"),
    path(
        "farmers/<int:pk>/",
        views.MobileFarmerDetailAPI.as_view(),
        name="mobile-farmer-detail",
    ),
    path("map/visits/", views.MobileVisitMapAPI.as_view(), name="mobile-map-visits"),
]
