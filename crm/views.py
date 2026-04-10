from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from utils.response import success_response, error_response
from utils.pagination import StandardPagination
from utils.schema import PAGINATION_PARAMS, SEARCH_PARAM, SIMPLE_SUCCESS, error_schema

from .models import Farmer, Visit, VisitReview
from .serializers import (
    FarmerSerializer,
    FarmerDetailSerializer,
    VisitSerializer,
    VisitReviewSerializer,
)


@extend_schema(
    tags=["Visits"],
    summary='Create visit review (CRM)",',
    description="Create a visit review linked to a farmer identified by phone number. Auto-creates farmer if not found.",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "example": "9876543210"},
                "name": {"type": "string"},
                "village": {"type": "string"},
                "crop": {"type": "string", "example": "Paddy"},
                "notes": {"type": "string"},
                "visit_date": {
                    "type": "string",
                    "format": "date",
                    "example": "2026-04-10",
                },
            },
            "required": ["phone", "crop", "notes", "visit_date"],
        }
    },
    responses={201: SIMPLE_SUCCESS, 400: error_schema("VisitReviewError")},
)
class VisitReviewCreateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        phone = request.data.get("phone")
        name = request.data.get("name")
        village = request.data.get("village")
        crop = request.data.get("crop")
        notes = request.data.get("notes")
        visit_date = request.data.get("visit_date")
        if not (phone and crop and notes and visit_date):
            return error_response(
                message="Missing required fields: phone, crop, notes, visit_date.",
                errors={"required": ["phone", "crop", "notes", "visit_date"]},
                code="VALIDATION_ERROR",
            )
        farmer, _ = Farmer.objects.get_or_create(
            phone=phone, defaults={"name": name or "", "village": village or ""}
        )
        visit, _ = Visit.objects.get_or_create(farmer=farmer, crop=crop)
        review = VisitReview.objects.create(
            visit=visit, notes=notes, visit_date=visit_date
        )
        return success_response(
            data={"review_id": review.id},
            message="Visit review created successfully",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Farmers"],
    summary="List farmers (CRM)",
    description="Paginated farmer list with visit statistics. Supports free-text search by name or phone.",
    parameters=[*PAGINATION_PARAMS, SEARCH_PARAM],
    responses={200: FarmerSerializer(many=True)},
)
class FarmerListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Farmer.objects.annotate(
            total_visits=Count("visits__reviews", distinct=True),
            last_visit_date=Max("visits__reviews__visit_date"),
        ).order_by("name")

        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(Q(name__icontains=search) | Q(phone__icontains=search))

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        data = FarmerSerializer(page, many=True).data
        return paginator.get_paginated_response(data)


@extend_schema(
    tags=["Farmers"],
    summary="Farmer detail (CRM)",
    description="Full farmer detail including all visits.",
    responses={200: FarmerDetailSerializer, 404: error_schema("FarmerNotFound")},
)
class FarmerDetailAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        return success_response(data=FarmerDetailSerializer(farmer).data)


@extend_schema(
    tags=["Visits"],
    summary="List visits by farmer (CRM)",
    description="Paginated visit list. Filter by `?farmer=<id>` to scope to one farmer.",
    parameters=[
        *PAGINATION_PARAMS,
        OpenApiParameter(
            "farmer", OpenApiTypes.INT, description="Filter by farmer ID."
        ),
    ],
    responses={200: VisitSerializer(many=True)},
)
class VisitListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        farmer_id = request.query_params.get("farmer")
        qs = Visit.objects.select_related("farmer").order_by("-id")
        if farmer_id:
            qs = qs.filter(farmer_id=farmer_id)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        data = VisitSerializer(page, many=True).data
        return paginator.get_paginated_response(data)
