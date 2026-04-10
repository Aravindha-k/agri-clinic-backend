from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404
from visits.models import Visit
from django.db.models import Q
from utils.schema import SIMPLE_SUCCESS


@extend_schema(
    tags=["Visits"],
    summary="Get or update visit details",
    description="Retrieve or update a visit by ID. PUT/PATCH supports full or partial updates.",
    request={"application/json": {"type": "object"}},
    responses={200: SIMPLE_SUCCESS},
)
class VisitDetailUpdateAPI(APIView):
    def get(self, request, id):
        try:
            visit = get_object_or_404(Visit, id=id)
            data = {
                "id": visit.id,
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
                "land_name": visit.land_name,
                "land_area": visit.land_area,
                "notes": visit.notes,
                "fertilizer_advice": visit.fertilizer_advice,
                "pesticide_advice": visit.pesticide_advice,
                "irrigation_advice": visit.irrigation_advice,
                "general_advice": visit.general_advice,
                "visit_date": visit.visit_date,
                "visit_time": visit.visit_time,
                "follow_up_required": visit.follow_up_required,
                "next_visit_date": visit.next_visit_date,
                "status": visit.status,
            }
            return Response(data)
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
        visit = get_object_or_404(Visit, id=id)
        user = request.user
        if not (user.is_staff or visit.employee_id == user.id):
            return Response({"error": "Forbidden"}, status=403)
        # Normalize phone
        phone = request.data.get("farmer_phone", visit.farmer_phone)
        if phone is not None:
            phone = phone.strip()
        # Update allowed fields only
        fields = [
            "farmer_name",
            "farmer_phone",
            "village_name",
            "crop_name",
            "crop_stage",
            "land_name",
            "land_area",
            "notes",
            "fertilizer_advice",
            "pesticide_advice",
            "irrigation_advice",
            "general_advice",
            "follow_up_required",
            "next_visit_date",
            "status",
        ]
        for field in fields:
            if field in request.data or not partial:
                value = request.data.get(field, getattr(visit, field, None))
                setattr(visit, field, value)
        visit.farmer_phone = phone
        visit.save()
        return Response({"success": True, "id": visit.id})
