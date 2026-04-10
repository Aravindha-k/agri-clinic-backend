from django.urls import path, include

from .views import MobileVisitStatsAPI

urlpatterns = [
    path("visits/stats/", MobileVisitStatsAPI.as_view(), name="mobile-visit-stats"),
    # Add other mobile API endpoints here
]
