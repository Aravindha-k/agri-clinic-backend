"""
Admin Crop → Pest/Disease mapping APIs.

Source of truth: CropProblem (not ProblemMaster.crop, not global fallback).

Disease category may be inactive for field/mobile; Admin reads still include it.
Does not activate Disease. Does not touch PM142 / Visits / mobile contract.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.views import APIView

from masters.models import Crop, CropProblem, ProblemCategory, ProblemMaster
from utils.permissions import IsStaffAdmin
from utils.response import error_response, success_response

# Legacy anomaly — never map as a Pest candidate / never accept for map.
PM142_NUTRIENT_MISFILE_ID = 142

ALLOWED_CODES = frozenset(
    {ProblemCategory.CODE_PEST, ProblemCategory.CODE_DISEASE}
)


def _crop_list_queryset():
    return Crop.objects.filter(is_active=True).annotate(
        pest_count=Count(
            "crop_problems",
            filter=Q(
                crop_problems__problem_master__category__code=ProblemCategory.CODE_PEST,
                crop_problems__problem_master__is_active=True,
            ),
            distinct=True,
        ),
        disease_count=Count(
            "crop_problems",
            filter=Q(
                crop_problems__problem_master__category__code=ProblemCategory.CODE_DISEASE,
                crop_problems__problem_master__is_active=True,
            ),
            distinct=True,
        ),
    ).order_by("name_en")


def _serialize_crop_row(crop: Crop) -> dict:
    return {
        "id": crop.id,
        "name": crop.name_en,
        "name_en": crop.name_en,
        "tamil_name": crop.name_ta or "",
        "name_ta": crop.name_ta or "",
        "is_active": crop.is_active,
        "pest_count": int(getattr(crop, "pest_count", 0) or 0),
        "disease_count": int(getattr(crop, "disease_count", 0) or 0),
    }


def _serialize_master(pm: ProblemMaster) -> dict:
    return {
        "id": pm.id,
        "name": pm.name,
        "tamil_name": pm.tamil_name or "",
        "is_active": pm.is_active,
        "category_id": pm.category_id,
        "category_code": pm.category.code if pm.category_id else "",
    }


def _mapped_masters_for_crop(crop_id: int, category_code: str):
    """Strict CropProblem-only listing — no global fallback. Returns only active masters."""
    return (
        ProblemMaster.objects.filter(
            crop_problems__crop_id=crop_id,
            category__code=category_code,
            is_active=True,
        )
        .select_related("category")
        .order_by("name", "id")
        .distinct()
    )


def _resolve_category(raw: str | None) -> ProblemCategory | None:
    if raw in (None, ""):
        return None
    raw = str(raw).strip().lower()
    if raw.isdigit():
        cat = ProblemCategory.objects.filter(pk=int(raw)).first()
    else:
        # Accept API aliases
        code = raw
        if code == "nutrient_issue":
            code = ProblemCategory.CODE_NUTRIENT
        cat = ProblemCategory.objects.filter(code=code).first()
    if cat is None or cat.code not in ALLOWED_CODES:
        return None
    return cat


@extend_schema(
    tags=["Admin", "Crop Pest Disease"],
    summary="Admin crop list with Pest/Disease CropProblem counts",
)
class AdminCropPestDiseaseListAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def get(self, request):
        qs = _crop_list_queryset()
        active = request.query_params.get("is_active")
        if active is not None and active != "":
            qs = qs.filter(is_active=str(active).lower() in {"1", "true", "yes"})
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(name_en__icontains=search) | Q(name_ta__icontains=search))
        rows = [_serialize_crop_row(c) for c in qs]
        return success_response(data={"count": len(rows), "results": rows})


@extend_schema(
    tags=["Admin", "Crop Pest Disease"],
    summary="Admin crop Pest/Disease mapping detail (CropProblem only)",
)
class AdminCropPestDiseaseDetailAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def get(self, request, crop_id: int):
        crop = get_object_or_404(Crop, pk=crop_id)
        pests = list(_mapped_masters_for_crop(crop.id, ProblemCategory.CODE_PEST))
        diseases = list(
            _mapped_masters_for_crop(crop.id, ProblemCategory.CODE_DISEASE)
        )
        return success_response(
            data={
                "crop": {
                    "id": crop.id,
                    "name": crop.name_en,
                    "name_en": crop.name_en,
                    "tamil_name": crop.name_ta or "",
                    "name_ta": crop.name_ta or "",
                    "is_active": crop.is_active,
                },
                "pests": [_serialize_master(p) for p in pests],
                "diseases": [_serialize_master(d) for d in diseases],
                "pest_count": len(pests),
                "disease_count": len(diseases),
            }
        )


@extend_schema(
    tags=["Admin", "Crop Pest Disease"],
    summary="Search Pest/Disease masters available to map to a crop",
)
class AdminCropAvailableMastersAPI(APIView):
    """
    Search ProblemMasters for mapping.

    Query:
      category=pest|disease (required)
      search=<text>
      include_mapped=true|false (default false → only unmapped to this crop)
    """

    permission_classes = [IsStaffAdmin]

    def get(self, request, crop_id: int):
        crop = get_object_or_404(Crop, pk=crop_id)
        cat = _resolve_category(request.query_params.get("category"))
        if cat is None:
            return error_response(
                message="category must be pest or disease",
                errors={"category": ["Required: pest or disease"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        mapped_ids = set(
            CropProblem.objects.filter(
                crop_id=crop.id, problem_master__category=cat
            ).values_list("problem_master_id", flat=True)
        )

        qs = ProblemMaster.objects.filter(category=cat, is_active=True).select_related("category")
        # Exclude PM142 from pest candidates always
        if cat.code == ProblemCategory.CODE_PEST:
            qs = qs.exclude(pk=PM142_NUTRIENT_MISFILE_ID)

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) | Q(tamil_name__icontains=search)
            )

        include_mapped = str(
            request.query_params.get("include_mapped") or ""
        ).lower() in {"1", "true", "yes"}
        if not include_mapped:
            qs = qs.exclude(id__in=mapped_ids)

        qs = qs.order_by("name", "id")
        limit = request.query_params.get("limit")
        try:
            limit_n = min(max(int(limit), 1), 200) if limit not in (None, "") else 100
        except (TypeError, ValueError):
            limit_n = 100
        rows = []
        for pm in qs[:limit_n]:
            item = _serialize_master(pm)
            item["already_mapped"] = pm.id in mapped_ids
            rows.append(item)

        return success_response(
            data={
                "crop_id": crop.id,
                "category": cat.code,
                "count": len(rows),
                "results": rows,
            }
        )


@extend_schema(
    tags=["Admin", "Crop Pest Disease"],
    summary="Map an existing ProblemMaster to a crop (CropProblem get_or_create)",
)
class AdminCropMapMasterAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def post(self, request, crop_id: int):
        crop = get_object_or_404(Crop, pk=crop_id)
        raw_id = request.data.get("problem_master_id")
        try:
            master_id = int(raw_id)
        except (TypeError, ValueError):
            return error_response(
                message="problem_master_id must be an integer PK",
                errors={"problem_master_id": ["Expected integer primary key"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if master_id == PM142_NUTRIENT_MISFILE_ID:
            return error_response(
                message="ProblemMaster 142 cannot be mapped via this API",
                errors={"problem_master_id": ["PM142 is excluded"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        master = (
            ProblemMaster.objects.select_related("category")
            .filter(pk=master_id)
            .first()
        )
        if master is None:
            return error_response(
                message="ProblemMaster not found",
                errors={"problem_master_id": ["Not found"]},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if not master.is_active:
            return error_response(
                message="Cannot map inactive ProblemMaster",
                errors={"problem_master_id": ["ProblemMaster must be active"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not master.category_id or master.category.code not in ALLOWED_CODES:
            return error_response(
                message="Only Pest or Disease masters can be mapped here",
                errors={"problem_master_id": ["Category must be pest or disease"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            link, created = CropProblem.objects.get_or_create(
                crop=crop, problem_master=master
            )

        return success_response(
            data={
                "crop_id": crop.id,
                "problem_master_id": master.id,
                "category_code": master.category.code,
                "created": created,
                "already_mapped": not created,
                "crop_problem_id": link.id,
                "master": _serialize_master(master),
            },
            message="Mapped" if created else "Already mapped",
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Admin", "Crop Pest Disease"],
    summary="Unmap ProblemMaster from crop (delete CropProblem only)",
)
class AdminCropUnmapMasterAPI(APIView):
    permission_classes = [IsStaffAdmin]

    def post(self, request, crop_id: int):
        return self._unmap(request, crop_id)

    def delete(self, request, crop_id: int):
        return self._unmap(request, crop_id)

    def _unmap(self, request, crop_id: int):
        crop = get_object_or_404(Crop, pk=crop_id)
        raw_id = request.data.get("problem_master_id")
        if raw_id in (None, "") and hasattr(request, "query_params"):
            raw_id = request.query_params.get("problem_master_id")
        try:
            master_id = int(raw_id)
        except (TypeError, ValueError):
            return error_response(
                message="problem_master_id must be an integer PK",
                errors={"problem_master_id": ["Expected integer primary key"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        master = ProblemMaster.objects.filter(pk=master_id).first()
        if master is None:
            return error_response(
                message="ProblemMaster not found",
                errors={"problem_master_id": ["Not found"]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        deleted_count, _ = CropProblem.objects.filter(
            crop=crop, problem_master_id=master_id
        ).delete()

        # Confirm master still exists
        still = ProblemMaster.objects.filter(pk=master_id).exists()
        return success_response(
            data={
                "crop_id": crop.id,
                "problem_master_id": master_id,
                "unmapped": deleted_count > 0,
                "crop_problem_rows_deleted": deleted_count,
                "problem_master_still_exists": still,
            },
            message="Unmapped" if deleted_count else "No mapping existed",
        )
