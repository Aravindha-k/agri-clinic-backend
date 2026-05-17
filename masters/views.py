# =========================
# Imports
# =========================
from .models import (
    FarmerField,
    FieldCrop,
    District,
    Village,
    Crop,
    Farmer,
    ProblemCategory,
)
from .serializers import (
    FarmerFieldSerializer,
    FieldCropSerializer,
    DistrictSerializer,
    VillageSerializer,
    CropSerializer,
    ProblemCategorySerializer,
    FarmerSerializer,
)
from rest_framework import viewsets, status, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS, BasePermission
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404

from utils.response import success_response, error_response

try:
    from django_filters.rest_framework import DjangoFilterBackend

    HAS_DJANGO_FILTER = True
except ImportError:
    HAS_DJANGO_FILTER = False


# =========================
# Permissions
# =========================
class IsAdminWriteEmployeeReadOnly(BasePermission):
    """
    Admin (is_staff=True) -> Full access
    Employee -> Read only
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_staff


# =========================
# Pagination
# =========================
class MasterPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


# =========================
# BaseMasterViewSet
# =========================
class BaseMasterViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsAdminWriteEmployeeReadOnly]
    pagination_class = MasterPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter] + (
        [DjangoFilterBackend] if HAS_DJANGO_FILTER else []
    )
    search_fields = ["name_en", "name_ta"]
    ordering_fields = ["name_en", "name_ta", "created_at", "is_active"]
    ordering = ["name_en"]

    def get_queryset(self):
        queryset = self.queryset
        if self.request.user.is_staff:
            show_inactive = self.request.query_params.get("show_inactive")
            if show_inactive == "true":
                return queryset.all()
        return queryset.filter(is_active=True)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        return success_response(message="Disabled successfully")

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        instance = self.queryset.filter(pk=pk).first()
        if not instance:
            return error_response(
                message="Object not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        instance.is_active = True
        instance.save()
        return success_response(message="Restored successfully")


# =========================
# ViewSets
# =========================
class DistrictViewSet(BaseMasterViewSet):
    queryset = District.objects.all()
    serializer_class = DistrictSerializer
    filterset_fields = ["is_active"] if HAS_DJANGO_FILTER else []
    search_fields = ["name"]
    ordering_fields = ["name"]
    ordering = ["name"]


class VillageViewSet(BaseMasterViewSet):
    queryset = Village.objects.all()
    serializer_class = VillageSerializer
    filterset_fields = ["district", "is_active"] if HAS_DJANGO_FILTER else []
    search_fields = ["name"]
    ordering_fields = ["name"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        district_id = self.request.query_params.get("district_id")
        if district_id:
            queryset = queryset.filter(district_id=district_id)
        return queryset


class CropViewSet(BaseMasterViewSet):
    queryset = Crop.objects.all()
    serializer_class = CropSerializer
    filterset_fields = ["is_active"] if HAS_DJANGO_FILTER else []
    pagination_class = None
    search_fields = ["name_en", "name_ta"]
    ordering_fields = ["name_en", "name_ta"]


class FarmerViewSet(BaseMasterViewSet):
    queryset = Farmer.objects.select_related(
        "village", "district", "assigned_employee", "created_by_employee"
    ).all()
    serializer_class = FarmerSerializer
    search_fields = ["name", "phone", "farmer_code", "village__name"]
    ordering_fields = ["name", "created_at", "phone", "farmer_code"]
    ordering = ["name"]
    filterset_fields = (
        ["village", "district", "created_by_employee", "assigned_employee"]
        if HAS_DJANGO_FILTER
        else []
    )

    def get_queryset(self):
        return self.queryset.order_by("name")

    def perform_create(self, serializer):
        serializer.save(created_by_employee=self.request.user)


class FarmerFieldViewSet(BaseMasterViewSet):
    queryset = FarmerField.objects.select_related("farmer", "created_by_employee").all()
    serializer_class = FarmerFieldSerializer
    search_fields = ["land_name", "farmer__name"]
    ordering_fields = ["land_name", "land_size", "created_at", "is_active"]
    ordering = ["land_name"]
    filterset_fields = (
        ["farmer", "is_active", "created_by_employee"] if HAS_DJANGO_FILTER else []
    )

    def perform_create(self, serializer):
        serializer.save(created_by_employee=self.request.user)


class FieldCropViewSet(BaseMasterViewSet):
    queryset = FieldCrop.objects.select_related("land", "crop").all()
    serializer_class = FieldCropSerializer
    search_fields = ["crop_name", "land__land_name"]
    ordering_fields = ["crop_name", "sowing_date", "created_at", "is_active"]
    ordering = ["-sowing_date"]
    filterset_fields = ["land", "crop", "is_active"] if HAS_DJANGO_FILTER else []


@extend_schema(
    tags=["Masters"],
    summary="List or create problem categories",
    request=ProblemCategorySerializer,
    responses={
        200: ProblemCategorySerializer(many=True),
        201: ProblemCategorySerializer,
    },
)
class ProblemCategoryListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        categories = ProblemCategory.objects.filter(is_active=True).order_by("name")
        serializer = ProblemCategorySerializer(categories, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
            }
        )

    def post(self, request):
        serializer = ProblemCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "success": True,
                    "message": "Category created",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(
            {
                "success": False,
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@extend_schema(
    tags=["Masters"],
    summary="Get or delete a problem category",
    responses={
        200: ProblemCategorySerializer,
        204: None,
    },
)
class ProblemCategoryDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminWriteEmployeeReadOnly]

    def get(self, request, category_id):
        category = get_object_or_404(ProblemCategory, id=category_id)
        serializer = ProblemCategorySerializer(category)
        return Response(
            {
                "success": True,
                "data": serializer.data,
            }
        )

    def delete(self, request, category_id):
        category = get_object_or_404(ProblemCategory, id=category_id)
        category.is_active = False
        category.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)
