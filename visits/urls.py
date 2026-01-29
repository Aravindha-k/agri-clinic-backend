from django.urls import path
from .views import (
    CreateVisitAPI,
    VisitListAPI,
    VisitAttachmentUploadAPI,
    VisitAttachmentDownloadAPI,
)

urlpatterns = [
    path("create/", CreateVisitAPI.as_view()),
    path("list/", VisitListAPI.as_view()),
    path("visits/<int:visit_id>/upload/", VisitAttachmentUploadAPI.as_view()),
    path(
        "files/<int:file_id>/download/",
        VisitAttachmentDownloadAPI.as_view(),
    ),
]
