"""Farmer profile photo upload APIs."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from api.admin.permissions import IsAdminUser
from mobile_api.device_session import DeviceSessionRequiredMixin
from mobile_api.permissions import IsEmployeeUser
from farmers.access import farmer_photo_editable_by
from farmers.serializers import FarmerListSerializer
from farmers.views import _farmers_queryset_for_user
from masters.models import Farmer
from utils.profile_photos import validate_profile_photo
from utils.response import error_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


def _save_farmer_photo(farmer: Farmer, file_obj, *, actor=None, request=None) -> Farmer:
    if farmer.profile_photo:
        farmer.profile_photo.delete(save=False)
    farmer.profile_photo = file_obj
    farmer.save(update_fields=["profile_photo"])
    try:
        from audit_logs.utils import create_audit_log

        create_audit_log(
            actor=actor,
            module="FARMERS",
            action="UPLOAD",
            object_id=farmer.pk,
            description=f"Farmer profile photo updated: {farmer.name}",
            request=request,
        )
    except Exception:
        pass
    return farmer


class BaseFarmerPhotoAPI(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def _get_farmer(self, pk):
        return get_object_or_404(_farmers_queryset_for_user(self.request.user), pk=pk)

    def _upload(self, request, pk):
        farmer = self._get_farmer(pk)
        if not farmer_photo_editable_by(request.user, farmer):
            return error_response(message="Not authorized", status_code=403)

        file_obj = request.FILES.get("profile_photo") or request.FILES.get("file")
        errors = validate_profile_photo(file_obj)
        if errors:
            return error_response(message="Validation failed", errors=errors, status_code=400)

        farmer = _save_farmer_photo(
            farmer, file_obj, actor=request.user, request=request
        )
        try:
            from farmers.services import invalidate_farmers_list_cache

            invalidate_farmers_list_cache()
        except Exception:
            pass

        return success_response(
            data=FarmerListSerializer(farmer, context={"request": request}).data,
            message="Farmer photo updated",
        )


@extend_schema(
    tags=["Farmers"],
    summary="Upload farmer profile photo",
    responses={200: SIMPLE_SUCCESS, 403: error_schema("Forbidden")},
)
class FarmerPhotoAPI(BaseFarmerPhotoAPI):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        return self._upload(request, pk)


@extend_schema(
    tags=["Admin", "Farmers"],
    summary="Upload farmer profile photo (admin)",
    responses={200: SIMPLE_SUCCESS},
)
class MobileFarmerPhotoAPI(DeviceSessionRequiredMixin, BaseFarmerPhotoAPI):
    permission_classes = [IsAuthenticated, IsEmployeeUser]


class AdminFarmerPhotoAPI(BaseFarmerPhotoAPI):
    permission_classes = [IsAdminUser]

    def _get_farmer(self, pk):
        return get_object_or_404(Farmer.objects.all(), pk=pk)

    def patch(self, request, pk):
        farmer = self._get_farmer(pk)
        file_obj = request.FILES.get("profile_photo") or request.FILES.get("file")
        errors = validate_profile_photo(file_obj)
        if errors:
            return error_response(message="Validation failed", errors=errors, status_code=400)

        farmer = _save_farmer_photo(
            farmer, file_obj, actor=request.user, request=request
        )
        return success_response(
            data=FarmerListSerializer(farmer, context={"request": request}).data,
            message="Farmer photo updated",
        )
