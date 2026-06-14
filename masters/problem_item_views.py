from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from masters.models import Crop, ProblemMaster
from masters.problem_item_import import import_problem_items_from_excel
from masters.problem_item_serializers import ProblemItemSerializer
from masters.problem_item_utils import db_category_code
from masters.problem_views import models_Q_crop_filter
from masters.serializers import CropSerializer
from utils.response import error_response, success_response


class ProblemItemPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


def _truthy_param(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes"}


def _apply_category_filter(qs, request):
    category = request.query_params.get("category")
    category_id = request.query_params.get("category_id")
    if category_id:
        return qs.filter(category_id=category_id)
    if category:
        try:
            db_code = db_category_code(category.strip().lower())
            return qs.filter(category__code=db_code)
        except ValueError:
            return qs.none()
    return qs


def _problem_item_queryset(request):
    qs = ProblemMaster.objects.filter(is_active=True).select_related("category", "crop")
    if request.user.is_staff and request.query_params.get("is_active") == "false":
        qs = ProblemMaster.objects.all().select_related("category", "crop")

    qs = _apply_category_filter(qs, request)

    crop_id = request.query_params.get("crop_id")
    search_all = _truthy_param(request.query_params.get("search_all"))
    if crop_id:
        crop_filtered = qs.filter(models_Q_crop_filter(crop_id))
        if search_all and not crop_filtered.exists():
            pass
        else:
            qs = crop_filtered

    search = (request.query_params.get("search") or "").strip()
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(tamil_name__icontains=search)

    is_active = request.query_params.get("is_active")
    if is_active is not None and is_active != "":
        if is_active.lower() in {"true", "1", "yes"}:
            qs = qs.filter(is_active=True)
        elif is_active.lower() in {"false", "0", "no"}:
            qs = qs.filter(is_active=False)

    return qs.order_by("category__name", "name")


@extend_schema(tags=["Masters", "Problem Items"], summary="List problem items")
class ProblemItemListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _problem_item_queryset(request)
        paginator = ProblemItemPagination()
        page = paginator.paginate_queryset(qs, request)
        rows = ProblemItemSerializer(page, many=True).data
        if page is not None:
            return success_response(
                data={
                    "count": paginator.page.paginator.count,
                    "next": paginator.get_next_link(),
                    "previous": paginator.get_previous_link(),
                    "results": rows,
                }
            )
        return success_response(data=rows)


@extend_schema(tags=["Masters", "Problem Items"], summary="Crop problem items")
class CropProblemItemListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, crop_id):
        get_object_or_404(Crop, pk=crop_id)
        qs = _problem_item_queryset(request).filter(models_Q_crop_filter(crop_id))
        paginator = ProblemItemPagination()
        page = paginator.paginate_queryset(qs, request)
        rows = ProblemItemSerializer(page, many=True).data
        if page is not None:
            return success_response(
                data={
                    "count": paginator.page.paginator.count,
                    "next": paginator.get_next_link(),
                    "previous": paginator.get_previous_link(),
                    "results": rows,
                }
            )
        return success_response(data=rows)


@extend_schema(tags=["Masters", "Crops"], summary="List crops")
class CropListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        crops = Crop.objects.filter(is_active=True).order_by("name_en")
        return success_response(data=CropSerializer(crops, many=True).data)


class ProblemItemViewSet(ModelViewSet):
    """Admin CRUD for Problem Items (ProblemMaster rows)."""

    serializer_class = ProblemItemSerializer
    permission_classes = [IsAdminUser]
    pagination_class = ProblemItemPagination
    queryset = ProblemMaster.objects.select_related("category", "crop").order_by(
        "category__name", "name"
    )
    search_fields = ["name", "tamil_name", "category__name", "crop__name_en"]

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get("category")
        if category:
            try:
                db_code = db_category_code(category.strip().lower())
                qs = qs.filter(category__code=db_code)
            except ValueError:
                return qs.none()
        crop_id = self.request.query_params.get("crop_id")
        if crop_id:
            qs = qs.filter(models_Q_crop_filter(crop_id))
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(tamil_name__icontains=search)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None and is_active != "":
            qs = qs.filter(is_active=is_active.lower() in {"true", "1", "yes"})
        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message="Problem item created",
            status_code=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return success_response(data=self.get_serializer(instance).data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Problem item updated")

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        return success_response(message="Problem item deactivated")


def _import_problem_items_from_upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        return error_response(
            message="Excel file is required.",
            errors={"file": ["No file uploaded. Use multipart field name 'file'."]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not upload.name.lower().endswith((".xlsx", ".xlsm")):
        return error_response(
            message="Invalid file type. Upload an .xlsx Excel file.",
            errors={"file": ["Only .xlsx files are supported."]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    summary = import_problem_items_from_excel(upload)
    if summary.failed_count and not summary.imported_count and not summary.updated_count:
        return error_response(
            message="Import failed.",
            errors={"import": summary.errors},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return success_response(
        data=summary.as_dict(),
        message="Import completed",
        status_code=status.HTTP_200_OK,
    )


@extend_schema(
    tags=["Masters", "Problem Masters"],
    summary="Import problem masters from Excel (pest sheet)",
)
class ProblemMasterImportAPI(APIView):
    """POST /api/v1/masters/problem-masters/import/ — matches admin Problem Items UI."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return error_response(
                message="Admin only",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return _import_problem_items_from_upload(request)


@extend_schema(
    tags=["Admin", "Problem Items"],
    summary="Import problem items from Excel",
)
class ProblemItemImportAPI(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        return _import_problem_items_from_upload(request)
