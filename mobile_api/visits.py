from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema
from .permissions import IsEmployeeUser
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema
from visits.models import Visit
from visits.serializers import VisitSerializer, VisitMediaUploadSerializer
from django.utils import timezone


@extend_schema(
    tags=["Mobile", "Visits"],
    summary="Mobile visits list/create",
    description="GET returns all visits for the logged-in employee. POST creates a visit and optionally uploads media files.",
    request=VisitSerializer,
    responses={
        200: VisitSerializer(many=True),
        201: VisitSerializer,
        400: error_schema("MobileVisitValidationError"),
    },
)
class MobileVisitListCreateAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        user = request.user
        visits = (
            Visit.objects.filter(employee=user)
            .select_related("village", "employee")
            .order_by("-visit_time")
        )
        serializer = VisitSerializer(visits, many=True)
        return success_response(data=serializer.data)

    def post(self, request):
        visit_serializer = VisitSerializer(
            data=request.data, context={"request": request}
        )
        if not visit_serializer.is_valid():
            return error_response(
                errors=visit_serializer.errors, message="Validation error"
            )
        visit = visit_serializer.save()
        # Handle media upload if present
        media_files = request.FILES.getlist("media")
        media_errors = []
        for file in media_files:
            media_type = request.data.get("media_type", "image")
            media_serializer = VisitMediaUploadSerializer(
                data={"file": file, "media_type": media_type}
            )
            if media_serializer.is_valid():
                media_serializer.save(visit=visit)
            else:
                media_errors.append(media_serializer.errors)
        if media_errors:
            return error_response(
                errors={"media": media_errors}, message="Media upload error"
            )
        return success_response(data={"visit_id": visit.id}, message="Visit created")
