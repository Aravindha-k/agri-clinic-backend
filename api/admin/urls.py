from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    FarmerViewSet,
    FarmerFieldViewSet,
    VisitViewSet,
    CropIssueViewSet,
    CropViewSet,
    FieldCropViewSet,
    RecommendationViewSet,
    DashboardStatsAPI,
)

router = DefaultRouter()
router.register(r"farmers", FarmerViewSet, basename="admin-farmer")
router.register(r"fields", FarmerFieldViewSet, basename="admin-field")
router.register(r"visits", VisitViewSet, basename="admin-visit")
router.register(r"issues", CropIssueViewSet, basename="admin-issue")
router.register(r"crops", FieldCropViewSet, basename="admin-crop")
router.register(r"crop-catalog", CropViewSet, basename="admin-crop-catalog")
router.register(
    r"recommendations", RecommendationViewSet, basename="admin-recommendation"
)

urlpatterns = [
    path("dashboard/stats/", DashboardStatsAPI.as_view(), name="dashboard-stats"),
    path(
        "crop-issues/",
        CropIssueViewSet.as_view({"get": "list"}),
        name="admin-crop-issue-list",
    ),
    path("", include(router.urls)),
]
