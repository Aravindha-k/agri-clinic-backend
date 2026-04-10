from django.urls import path
from .views import VisitReviewCreateAPI, FarmerListAPI, FarmerDetailAPI, VisitListAPI

urlpatterns = [
    path("visits/review", VisitReviewCreateAPI.as_view()),
    path("farmers", FarmerListAPI.as_view()),
    path("farmers/<int:pk>", FarmerDetailAPI.as_view()),
    path("visits", VisitListAPI.as_view()),
]
