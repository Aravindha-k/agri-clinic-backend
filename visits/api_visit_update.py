from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404
from django.http import Http404
from visits.models import Visit
from visits.access import is_privileged_user, visits_for_user
from visits.api_fields import strip_visit_status_from_representation
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE, visit_has_submitted_details
from django.db.models import Q
from utils.schema import SIMPLE_SUCCESS
from masters.models import Farmer, FarmerField, Crop, Village


VISIT_STATUS_VALUES = {c[0] for c in Visit.STATUS_CHOICES}


@extend_schema(
    tags=["Visits"],
    summary="Get or update visit details",
    description="Retrieve or update a visit by ID. PUT/PATCH supports full or partial updates.",
    request={"application/json": {"type": "object"}},
    responses={200: SIMPLE_SUCCESS},
)
class VisitDetailUpdateAPI(APIView):
    permission_classes = [IsAuthenticated]

    def _get_scoped_visit(self, request, id):
        qs = visits_for_user(request.user).select_related(
            "employee",
            "employee__employee_profile",
            "district",
            "village",
            "crop",
            "farmer",
            "field",
        )
        return get_object_or_404(qs, id=id)

    def get(self, request, id):
        try:
            visit = self._get_scoped_visit(request, id)
            data = {
                "id": visit.id,
                "employee": {
                    "id": visit.employee_id,
                    "username": visit.employee.username,
                    "first_name": visit.employee.first_name or "",
                    "last_name": visit.employee.last_name or "",
                    "employee_id": getattr(
                        getattr(visit.employee, "employee_profile", None),
                        "employee_id",
                        None,
                    ),
                },
                "employee_name": visit.employee.get_full_name() or visit.employee.username,
                "employee_phone": getattr(
                    getattr(visit.employee, "employee_profile", None),
                    "phone",
                    "",
                )
                or "",
                "farmer": (
                    {
                        "id": visit.farmer_id,
                        "name": visit.farmer.name,
                        "phone": visit.farmer.phone,
                        "farmer_code": visit.farmer.farmer_code,
                    }
                    if visit.farmer_id
                    else None
                ),
                "field": (
                    {
                        "id": visit.field_id,
                        "land_name": visit.field.land_name,
                        "land_size": visit.field.land_size,
                        "gps_location": visit.field.gps_location,
                    }
                    if visit.field_id
                    else None
                ),
                "farmer_name": visit.farmer_name,
                "farmer_phone": visit.farmer_phone,
                "village_name": (
                    visit.village.name
                    if visit.village
                    else getattr(visit, "village_name", None)
                ),
                "district_name": visit.district.name if visit.district else None,
                "crop_name": visit.crop.name_en if visit.crop else None,
                "crop_stage": visit.crop_stage,
                "crop_health": visit.crop_health,
                "pest_issue": visit.pest_issue,
                "disease_issue": visit.disease_issue,
                "weed_condition": visit.weed_condition,
                "land_name": visit.land_name,
                "land_area": visit.land_area,
                "notes": visit.notes,
                "fertilizer_advice": visit.fertilizer_advice,
                "pesticide_advice": visit.pesticide_advice,
                "irrigation_advice": visit.irrigation_advice,
                "general_advice": visit.general_advice,
                "visit_date": visit.visit_date,
                "visit_time": visit.visit_time,
                "latitude": visit.latitude,
                "longitude": visit.longitude,
                "follow_up_required": visit.follow_up_required,
                "next_visit_date": visit.next_visit_date,
                "created_at": visit.created_at,
                "updated_at": visit.updated_at,
            }
            return Response(strip_visit_status_from_representation(data))
        except Http404:
            raise
        except Exception as e:
            print("ERROR:", e)
            return Response(
                {
                    "success": False,
                    "error": {"code": "INTERNAL_ERROR", "message": str(e)},
                },
                status=500,
            )

    def put(self, request, id):
        return self._update(request, id, partial=False)

    def patch(self, request, id):
        return self._update(request, id, partial=True)

    def _update(self, request, id, partial):
        visit = self._get_scoped_visit(request, id)
        # Normalize phone
        phone = request.data.get("farmer_phone", visit.farmer_phone)
        if phone is not None:
            phone = phone.strip()
        # Update allowed fields only
        fields = [
            "farmer_name",
            "farmer_phone",
            "crop_stage",
            "crop_health",
            "pest_issue",
            "disease_issue",
            "weed_condition",
            "land_name",
            "land_area",
            "notes",
            "fertilizer_advice",
            "pesticide_advice",
            "irrigation_advice",
            "general_advice",
            "follow_up_required",
            "latitude",
            "longitude",
            "next_visit_date",
        ]
        for field in fields:
            if field in request.data or not partial:
                value = request.data.get(field, getattr(visit, field, None))
                if field == "land_area" and value == "":
                    value = None
                if field in {"latitude", "longitude"} and value == "":
                    value = None
                if field in {"latitude", "longitude"} and value not in (None, ""):
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        return Response(
                            {
                                "success": False,
                                "error": {
                                    "code": "VALIDATION_ERROR",
                                    "message": f"Invalid {field}",
                                },
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                if field == "next_visit_date" and value == "":
                    value = None
                setattr(visit, field, value)

        if "crop_name" in request.data:
            crop_label = (request.data.get("crop_name") or "").strip()
            if crop_label:
                crop = Crop.objects.filter(
                    Q(name_en__iexact=crop_label) | Q(name_ta__iexact=crop_label)
                ).order_by("id").first()
                if crop:
                    visit.crop = crop

        if "village_name" in request.data:
            village_label = (request.data.get("village_name") or "").strip()
            if village_label:
                village = (
                    Village.objects.filter(name__iexact=village_label)
                    .order_by("id")
                    .first()
                )
                if village:
                    visit.village = village

        visit.farmer_phone = phone
        farmer = None
        if visit.farmer_id:
            farmer = visit.farmer
        if phone:
            farmer = Farmer.objects.filter(phone=phone).order_by("id").first()
        if farmer is None and visit.farmer_name:
            farmer = (
                Farmer.objects.filter(name__iexact=visit.farmer_name)
                .order_by("id")
                .first()
            )
        if farmer:
            visit.farmer = farmer
            if not visit.farmer_name:
                visit.farmer_name = farmer.name
            if not visit.farmer_phone:
                visit.farmer_phone = farmer.phone
            if not visit.district_id:
                visit.district = farmer.district
            if not visit.village_id:
                visit.village = farmer.village
            if visit.land_name:
                visit.field = (
                    FarmerField.objects.filter(
                        farmer=farmer, land_name__iexact=visit.land_name
                    )
                    .order_by("id")
                    .first()
                )
        if not visit_has_submitted_details(visit):
            return Response(
                {
                    "success": False,
                    "message": SUBMIT_VISIT_REQUIRED_MESSAGE,
                    "errors": {},
                    "code": "VALIDATION_ERROR",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        visit.save()
        try:
            from visits.views import _invalidate_visit_caches

            _invalidate_visit_caches()
        except Exception:
            pass
        return Response({"success": True, "id": visit.id})
