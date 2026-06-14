from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from masters.models import Crop, ProblemCategory, ProblemMaster, Village
from masters.problem_item_utils import problem_categories_with_active_items
from masters.problem_serializers import (
    ProblemCategoryDropdownSerializer,
    ProblemCategorySerializer,
    ProblemMasterDropdownSerializer,
    ProblemMasterSerializer,
)
from utils.response import success_response, error_response


def _problem_master_dropdown_qs(category_id=None, crop_id=None):
    qs = ProblemMaster.objects.filter(is_active=True).select_related("category", "crop")
    if category_id:
        qs = qs.filter(category_id=category_id)
    if crop_id:
        qs = qs.filter(models_Q_crop_filter(crop_id))
    return qs.order_by("category__name", "name")


def models_Q_crop_filter(crop_id):
    from django.db.models import Q

    return Q(crop_id__isnull=True) | Q(crop_id=crop_id)


@extend_schema(tags=["Masters", "Field Visit"], summary="Problem categories dropdown")
class ProblemCategoryDropdownAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = problem_categories_with_active_items()
        return success_response(
            data=ProblemCategoryDropdownSerializer(rows, many=True).data
        )


@extend_schema(
    tags=["Masters", "Field Visit"],
    summary="Problem masters dropdown",
    parameters=[],
)
class ProblemMasterDropdownAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        category_id = request.query_params.get("category_id") or request.query_params.get(
            "problem_category_id"
        )
        crop_id = request.query_params.get("crop_id")
        qs = _problem_master_dropdown_qs(category_id=category_id, crop_id=crop_id)
        rows = ProblemMasterDropdownSerializer(qs, many=True).data
        return success_response(
            data={"problem_masters": rows, "problem_subcategories": rows}
        )


@extend_schema(
    tags=["Masters", "Field Visit"],
    summary="Visit form dropdown options (villages, crops, problems)",
)
class VisitFormOptionsAPI(APIView):
    """Shared read-only options for admin + mobile Add Visit forms."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        category_id = request.query_params.get("category_id")
        crop_id = request.query_params.get("crop_id")

        villages = Village.objects.filter(is_active=True).select_related("district")
        crops = Crop.objects.filter(is_active=True).order_by("name_en")
        categories = problem_categories_with_active_items()
        masters = _problem_master_dropdown_qs(category_id=category_id, crop_id=crop_id)

        village_rows = [
            {
                "id": v.id,
                "name": v.name,
                "district_id": v.district_id,
                "district_name": v.district.name if v.district_id else "",
            }
            for v in villages
        ]
        crop_rows = [
            {"id": c.id, "name_en": c.name_en, "name_ta": c.name_ta}
            for c in crops
        ]

        master_rows = ProblemMasterDropdownSerializer(masters, many=True).data
        category_rows = ProblemCategoryDropdownSerializer(categories, many=True).data
        return success_response(
            data={
                "villages": village_rows,
                "crops": crop_rows,
                "problem_categories": category_rows,
                "problem_masters": master_rows,
                "problem_subcategories": master_rows,
            }
        )


@extend_schema(tags=["Masters", "Field Visit"], summary="Villages dropdown")
class VillageDropdownAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        villages = Village.objects.filter(is_active=True).select_related("district")
        rows = [
            {
                "id": v.id,
                "name": v.name,
                "district_id": v.district_id,
                "district_name": v.district.name if v.district_id else "",
            }
            for v in villages.order_by("name")
        ]
        return success_response(data=rows)


@extend_schema(tags=["Masters", "Field Visit"], summary="Crops dropdown")
class CropDropdownAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        crops = Crop.objects.filter(is_active=True).order_by("name_en")
        rows = [{"id": c.id, "name_en": c.name_en, "name_ta": c.name_ta} for c in crops]
        return success_response(data=rows)


@extend_schema(tags=["Masters"], summary="List or create problem categories")
class ProblemCategoryListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        categories = problem_categories_with_active_items()
        return success_response(
            data=ProblemCategorySerializer(categories, many=True).data
        )

    def post(self, request):
        if not request.user.is_staff:
            return error_response(message="Admin only", status_code=status.HTTP_403_FORBIDDEN)
        serializer = ProblemCategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message="Category created",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Masters"], summary="Get, update, or deactivate problem category")
class ProblemCategoryDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, category_id):
        category = get_object_or_404(ProblemCategory, pk=category_id)
        return success_response(data=ProblemCategorySerializer(category).data)

    def put(self, request, category_id):
        return self._update(request, category_id, partial=False)

    def patch(self, request, category_id):
        return self._update(request, category_id, partial=True)

    def _update(self, request, category_id, partial):
        if not request.user.is_staff:
            return error_response(message="Admin only", status_code=status.HTTP_403_FORBIDDEN)
        category = get_object_or_404(ProblemCategory, pk=category_id)
        serializer = ProblemCategorySerializer(
            category, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Category updated")

    def delete(self, request, category_id):
        if not request.user.is_staff:
            return error_response(message="Admin only", status_code=status.HTTP_403_FORBIDDEN)
        category = get_object_or_404(ProblemCategory, pk=category_id)
        category.is_active = False
        category.save(update_fields=["is_active"])
        return success_response(message="Category deactivated")


@extend_schema(tags=["Masters"], summary="List or create problem masters")
class ProblemMasterListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import logging

        logger = logging.getLogger(__name__)
        category_id = request.query_params.get("category_id")
        category = request.query_params.get("category")
        crop_id = request.query_params.get("crop_id")
        qs = ProblemMaster.objects.filter(is_active=True).select_related("category", "crop")
        if category_id:
            qs = qs.filter(category_id=category_id)
        if category:
            qs = qs.filter(category__code=category.strip().lower())
        if crop_id:
            qs = qs.filter(models_Q_crop_filter(crop_id))
        qs = qs.order_by("category__name", "name")
        logger.info(
            "ProblemMasterListCreateAPIView.get user_id=%s params=%s count=%s",
            getattr(request.user, "id", None),
            dict(request.query_params),
            qs.count(),
        )
        serializer = ProblemMasterSerializer(qs, many=True)
        return success_response(data=serializer.data)

    def post(self, request):
        if not request.user.is_staff:
            return error_response(message="Admin only", status_code=status.HTTP_403_FORBIDDEN)
        serializer = ProblemMasterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message="Problem master created",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Masters"], summary="Get, update, or deactivate problem master")
class ProblemMasterDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, master_id):
        row = get_object_or_404(
            ProblemMaster.objects.select_related("category", "crop"), pk=master_id
        )
        return success_response(data=ProblemMasterSerializer(row).data)

    def put(self, request, master_id):
        return self._update(request, master_id, partial=False)

    def patch(self, request, master_id):
        return self._update(request, master_id, partial=True)

    def _update(self, request, master_id, partial):
        if not request.user.is_staff:
            return error_response(message="Admin only", status_code=status.HTTP_403_FORBIDDEN)
        row = get_object_or_404(ProblemMaster, pk=master_id)
        serializer = ProblemMasterSerializer(row, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Problem master updated")

    def delete(self, request, master_id):
        if not request.user.is_staff:
            return error_response(message="Admin only", status_code=status.HTTP_403_FORBIDDEN)
        row = get_object_or_404(ProblemMaster, pk=master_id)
        row.is_active = False
        row.save(update_fields=["is_active"])
        return success_response(message="Problem master deactivated")
