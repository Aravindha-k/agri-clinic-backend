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
    ProblemCategoryViewSet,
    ProblemMasterViewSet,
    DashboardStatsAPI,
    DashboardOverviewAPI,
    FarmerVisitAuditAPI,
)
from masters.problem_views import VisitFormOptionsAPI
from masters.problem_item_views import ProblemItemViewSet, ProblemItemImportAPI
from .dev_reset import DevResetTestBusinessDataAPI
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
router.register(
    r"problem-categories",
    ProblemCategoryViewSet,
    basename="admin-problem-category",
)
router.register(
    r"problem-masters", ProblemMasterViewSet, basename="admin-problem-master"
)
router.register(
    r"problem-items", ProblemItemViewSet, basename="admin-problem-item"
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
    path(
        "visit-form-options/",
        VisitFormOptionsAPI.as_view(),
        name="admin-visit-form-options",
    ),
    path(
        "problem-items/import/",
        ProblemItemImportAPI.as_view(),
        name="admin-problem-items-import",
    ),
    path(
        "dev/reset-test-data/",
        DevResetTestBusinessDataAPI.as_view(),
        name="admin-dev-reset-test-data",
    ),
    path("", include(router.urls)),
]
