from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import (
    DistrictViewSet,
    VillageViewSet,
    CropViewSet,
    FarmerViewSet,
    FarmerFieldViewSet,
    FieldCropViewSet,
)
from .problem_views import (
    ProblemCategoryListCreateAPIView,
    ProblemCategoryDetailAPIView,
    ProblemMasterListCreateAPIView,
    ProblemMasterDetailAPIView,
    ProblemCategoryDropdownAPI,
    ProblemMasterDropdownAPI,
    VisitFormOptionsAPI,
    VillageDropdownAPI,
    CropDropdownAPI,
)
from .problem_item_views import ProblemItemListAPI, ProblemMasterImportAPI

router = DefaultRouter()
router.register(r"districts", DistrictViewSet)
router.register(r"villages", VillageViewSet)
router.register(r"crops", CropViewSet, basename="crop")
router.register(r"farmers", FarmerViewSet)
router.register(r"lands", FarmerFieldViewSet)
router.register(r"field-crops", FieldCropViewSet)

urlpatterns = [
    # Before router.urls so "villages/dropdown" is not captured as villages/<pk>.
    path("villages/dropdown/", VillageDropdownAPI.as_view(), name="villages-dropdown"),
    path("crops/dropdown/", CropDropdownAPI.as_view(), name="crops-dropdown"),
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
    path(
        "problem-categories/dropdown/",
        ProblemCategoryDropdownAPI.as_view(),
        name="problem-categories-dropdown",
    ),
    path(
        "problem-masters/",
        ProblemMasterListCreateAPIView.as_view(),
        name="problem-masters-list-create",
    ),
    path(
        "problem-masters/dropdown/",
        ProblemMasterDropdownAPI.as_view(),
        name="problem-masters-dropdown",
    ),
    path(
        "problem-masters/import/",
        ProblemMasterImportAPI.as_view(),
        name="problem-masters-import",
    ),
    path(
        "problem-masters/<int:master_id>/",
        ProblemMasterDetailAPIView.as_view(),
        name="problem-masters-detail",
    ),
    path(
        "visit-form-options/",
        VisitFormOptionsAPI.as_view(),
        name="visit-form-options",
    ),
    path(
        "problem-subcategories/",
        ProblemMasterListCreateAPIView.as_view(),
        name="problem-subcategories-list-create",
    ),
    path(
        "problem-subcategories/dropdown/",
        ProblemMasterDropdownAPI.as_view(),
        name="problem-subcategories-dropdown",
    ),
    path(
        "problem-subcategories/<int:master_id>/",
        ProblemMasterDetailAPIView.as_view(),
        name="problem-subcategories-detail",
    ),
    path("problem-items/", ProblemItemListAPI.as_view(), name="masters-problem-items-list"),
]
