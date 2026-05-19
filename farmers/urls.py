from django.urls import path

from .photo_views import FarmerPhotoAPI
from .views import (
    FarmerListCreateAPI,
    FarmerStatsAPI,
    FarmerDetailAPI,
    FarmerFieldListCreateAPI,
    FieldCropCreateAPI,
    VisitListCreateAPI,
    FarmerVisitListAPI,
    VisitIssueCreateAPI,
    CropIssueListAPI,
    VisitMediaUploadAPI,
    FarmerActivityListAPI,
    CropMasterListCreateAPI,
    RecommendationCreateAPI,
    RecommendIssueAPIView,
)

app_name = "farmers"

urlpatterns = [
    # ── Farmers ────────────────────────────────
    path("farmers/", FarmerListCreateAPI.as_view(), name="farmer-list-create"),
    path("farmers/stats/", FarmerStatsAPI.as_view(), name="farmer-stats"),
    path("farmers/<int:pk>/", FarmerDetailAPI.as_view(), name="farmer-detail"),
    path(
        "farmers/<int:pk>/photo/",
        FarmerPhotoAPI.as_view(),
        name="farmer-photo",
    ),
    # ── Farmer Fields ──────────────────────────
    path(
        "farmers/<int:farmer_id>/fields/",
        FarmerFieldListCreateAPI.as_view(),
        name="farmer-field-list-create",
    ),
    # ── Field crops ────────────────────────────
    path(
        "fields/<int:field_id>/crops/",
        FieldCropCreateAPI.as_view(),
        name="field-crop-create",
    ),
    # ── Farmer visits ──────────────────────────
    path(
        "farmers/<int:farmer_id>/visits/",
        FarmerVisitListAPI.as_view(),
        name="farmer-visit-list",
    ),
    # ── Visits (global) ────────────────────────
    path("visits/", VisitListCreateAPI.as_view(), name="visit-list-create"),
    # ── Crop issues ────────────────────────────
    path(
        "visits/<int:visit_id>/issues/",
        VisitIssueCreateAPI.as_view(),
        name="visit-issue-create",
    ),
    path("issues/", CropIssueListAPI.as_view(), name="issue-list"),
    path("crop-issues/", CropIssueListAPI.as_view(), name="crop-issue-list"),
    # ── Visit media ────────────────────────────
    path(
        "visits/<int:visit_id>/media/",
        VisitMediaUploadAPI.as_view(),
        name="visit-media-upload",
    ),
    # ── Recommendations (admin only) ──────────
    path(
        "issues/<int:issue_id>/recommendations/",
        RecommendationCreateAPI.as_view(),
        name="recommendation-create",
    ),
    path(
        "issues/<int:issue_id>/recommend/",
        RecommendIssueAPIView.as_view(),
        name="recommend-issue",
    ),
    # ── Farmer Activity Timeline ───────────────
    path(
        "farmers/<int:farmer_id>/activity/",
        FarmerActivityListAPI.as_view(),
        name="farmer-activity-list",
    ),
    # ── Crop Master Catalog ────────────────────
    path(
        "crop-catalog/",
        CropMasterListCreateAPI.as_view(),
        name="crop-master-list-create",
    ),
]
