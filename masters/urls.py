from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import (
    DistrictViewSet,
    VillageViewSet,
    CropViewSet,
    FarmerViewSet,
    FarmerFieldViewSet,
    FieldCropViewSet,
    ProblemCategoryListCreateAPIView,
    ProblemCategoryDetailAPIView,
)

router = DefaultRouter()
router.register(r"districts", DistrictViewSet)
router.register(r"villages", VillageViewSet)
router.register(r"crops", CropViewSet, basename="crop")
router.register(r"farmers", FarmerViewSet)
router.register(r"lands", FarmerFieldViewSet)
router.register(r"field-crops", FieldCropViewSet)

urlpatterns = [
    *router.urls,
    path(
        "problem-categories/",
        ProblemCategoryListCreateAPIView.as_view(),
        name="problem-categories-list-create",
    ),
    path(
        "problem-categories/<int:category_id>/",
        ProblemCategoryDetailAPIView.as_view(),
        name="problem-categories-detail",
    ),
]
