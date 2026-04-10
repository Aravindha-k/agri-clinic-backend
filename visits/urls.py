from django.urls import path, include
from .api_visit_update import VisitDetailUpdateAPI
from .views import (
    VisitListCreateAPI,
    VisitStatsAPI,
    VisitPhotoUploadAPI,
    BulkVisitUploadAPI,
    CompleteVisitAPI,
    VisitMediaUploadAPIView,
    VisitAttachmentUploadAPI,
    VisitAttachmentDownloadAPI,
    StartVisitAPI,
    ActiveVisitAPI,
)
from .api_visit_update import VisitDetailUpdateAPI

urlpatterns = [
    # --- CRITICAL: Add explicit update route first to prevent shadowing ---
    path("<int:id>/", VisitDetailUpdateAPI.as_view(), name="visit-update"),
    # Farmer aggregation APIs
    path("", include("visits.api_farmers_urls")),
    # ...existing visit APIs...
    path("", VisitListCreateAPI.as_view(), name="visit-list-create"),
    path("start/", StartVisitAPI.as_view(), name="visit-start"),
    path("active/", ActiveVisitAPI.as_view(), name="visit-active"),
    path("stats/", VisitStatsAPI.as_view(), name="visit-stats"),
    path("upload-photo/", VisitPhotoUploadAPI.as_view(), name="visit-photo-upload"),
    path("bulk/", BulkVisitUploadAPI.as_view(), name="bulk-visit-upload"),
    # path("<int:id>/", VisitDetailAPI.as_view(), name="visit-detail"),  # Disabled in favor of VisitDetailUpdateAPI
    path("<int:id>/complete/", CompleteVisitAPI.as_view(), name="complete-visit"),
    path(
        "<int:id>/upload-media/",
        VisitMediaUploadAPIView.as_view(),
        name="visit-media-upload",
    ),
    path(
        "<int:visit_id>/attachments/",
        VisitAttachmentUploadAPI.as_view(),
        name="visit-attachment-upload",
    ),
    path(
        "<int:file_id>/download/",
        VisitAttachmentDownloadAPI.as_view(),
        name="visit-attachment-download",
    ),
]
