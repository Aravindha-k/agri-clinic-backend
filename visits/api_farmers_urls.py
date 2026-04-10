from django.urls import path

from .api_farmers import FarmerSummaryAPI, FarmerDetailAPI
from .api_visit_update import VisitDetailUpdateAPI

urlpatterns = [
    path("farmers", FarmerSummaryAPI.as_view(), name="farmer-summary"),
    path("farmers/<str:phone>", FarmerDetailAPI.as_view(), name="farmer-detail"),
    path("visits/<int:id>", VisitDetailUpdateAPI.as_view(), name="visit-detail-update"),
]
