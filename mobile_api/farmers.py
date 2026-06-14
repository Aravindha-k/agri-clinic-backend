import logging

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated

from visits.farmer_visit_summary import (
    build_farmer_revisit_summary,
    build_farmer_visit_history,
)
from farmers.serializers import FarmerFieldSerializer, FarmerListSerializer
from farmers.views import StandardPagination, _farmers_queryset_with_visit_counts
from utils.response import success_response
from utils.schema import SIMPLE_SUCCESS, error_schema

from .device_session import MobileEmployeeAPIView
from .permissions import IsEmployeeUser

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Mobile", "Farmers"],
    summary="Mobile farmers list",
    description=(
        "Paginated directory of all farmers. "
        "Alias of GET /api/v1/farmers/ with employee-only guard."
    ),
    responses={200: FarmerListSerializer(many=True), 403: error_schema("Forbidden")},
)
class MobileFarmerListAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        farmers = _farmers_queryset_with_visit_counts(request.user).order_by("name")
        search = (request.query_params.get("search") or "").strip()
        if search:
            farmers = farmers.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(farmer_code__icontains=search)
                | Q(village__name__icontains=search)
            )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(farmers, request)
        serializer = FarmerListSerializer(page, many=True, context={"request": request})
        logger.info(
            "MobileFarmerList count=%s search=%s",
            paginator.page.paginator.count if page is not None else 0,
            search or None,
        )
        return paginator.get_paginated_response(serializer.data)


@extend_schema(
    tags=["Mobile", "Farmers"],
    summary="Mobile farmer detail",
    description="Farmer profile with active fields for the mobile detail screen.",
    responses={200: FarmerListSerializer, 404: error_schema("FarmerNotFound")},
)
class MobileFarmerDetailAPI(MobileEmployeeAPIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request, pk):
        farmer = get_object_or_404(
            _farmers_queryset_with_visit_counts(request.user)
            .select_related("village", "district", "assigned_employee")
            .prefetch_related("fields__crops__crop"),
            pk=pk,
        )
        data = FarmerListSerializer(farmer, context={"request": request}).data
        data["fields"] = FarmerFieldSerializer(
            farmer.fields.filter(is_active=True).prefetch_related("crops__crop"),
            many=True,
            context={"request": request},
        ).data
        data["visit_summary"] = build_farmer_revisit_summary(
            farmer, employee=request.user
        )
        data["visit_history"] = build_farmer_visit_history(
            farmer, employee=request.user, limit=20
        )
        return success_response(data=data, message="Farmer fetched")
