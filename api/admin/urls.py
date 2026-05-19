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
    DashboardOverviewAPI,
    FarmerVisitAuditAPI,
)
from visits.attachment_views import AdminVisitAttachmentListAPI
from accounts.profile_photos import AdminEmployeePhotoAPI
from farmers.photo_views import AdminFarmerPhotoAPI

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
    path(
        "audit/farmer-visits/",
        FarmerVisitAuditAPI.as_view(),
        name="admin-farmer-visit-audit",
    ),
    path("dashboard/stats/", DashboardStatsAPI.as_view(), name="dashboard-stats"),
    path(
        "dashboard/overview/",
        DashboardOverviewAPI.as_view(),
        name="dashboard-overview",
    ),
    path(
        "crop-issues/",
        CropIssueViewSet.as_view({"get": "list"}),
        name="admin-crop-issue-list",
    ),
    path(
        "visits/<int:visit_id>/attachments/",
        AdminVisitAttachmentListAPI.as_view(),
        name="admin-visit-attachments",
    ),
    path(
        "employees/<int:pk>/photo/",
        AdminEmployeePhotoAPI.as_view(),
        name="admin-employee-photo",
    ),
    path(
        "farmers/<int:pk>/photo/",
        AdminFarmerPhotoAPI.as_view(),
        name="admin-farmer-photo",
    ),
    path("", include(router.urls)),
]
