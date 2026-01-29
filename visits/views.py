from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .serializers import VisitCreateSerializer
from .models import Visit
from accounts.models import EmployeeProfile

from .models import Visit, VisitAttachment
from django.shortcuts import get_object_or_404
from django.http import FileResponse


class CreateVisitAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VisitCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        visit = serializer.save()

        return Response(
            {
                "message": "Visit created",
                "visit_id": visit.id,
                "visit_time": visit.visit_time,
            },
            status=status.HTTP_201_CREATED,
        )


class VisitListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        # ✅ ADMIN VIEW (All visits)
        if request.user.is_staff:
            visits = (
                Visit.objects.select_related("user")
                .prefetch_related("attachments")
                .order_by("-visit_time")
            )

            data = []
            for v in visits:
                try:
                    emp = v.user.employeeprofile
                    employee_id = emp.employee_id
                except EmployeeProfile.DoesNotExist:
                    employee_id = None

                # ✅ Attachments list
                attachments = [
                    {
                        "id": a.id,
                        "file_type": a.file_type,
                        "file": a.file.url,
                        "uploaded_at": a.uploaded_at,
                    }
                    for a in v.attachments.all()
                ]

                data.append(
                    {
                        "visit_id": v.id,
                        "employee_id": employee_id,
                        "employee_username": v.user.username,
                        "farmer_name": v.farmer_name,
                        "village": v.village,
                        "visit_time": v.visit_time,
                        "attachments": attachments,  # ✅ ADDED
                    }
                )

            return Response(data)

        # ✅ EMPLOYEE VIEW (Only their visits)
        visits = (
            Visit.objects.filter(user=request.user)
            .prefetch_related("attachments")
            .order_by("-visit_time")
        )

        data = []
        for v in visits:
            attachments = [
                {
                    "id": a.id,
                    "file_type": a.file_type,
                    "file": a.file.url,
                    "uploaded_at": a.uploaded_at,
                }
                for a in v.attachments.all()
            ]

            data.append(
                {
                    "visit_id": v.id,
                    "farmer_name": v.farmer_name,
                    "village": v.village,
                    "visit_time": v.visit_time,
                    "attachments": attachments,  # ✅ ADDED
                }
            )

        return Response(data)


class VisitAttachmentUploadAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, visit_id):
        try:
            visit = Visit.objects.get(id=visit_id)
        except Visit.DoesNotExist:
            return Response({"error": "Visit not found"}, status=404)

        uploaded_file = request.FILES.get("file")
        file_type = request.data.get("file_type", "OTHER")

        if not uploaded_file:
            return Response({"error": "File is required"}, status=400)

        attachment = VisitAttachment.objects.create(
            visit=visit,
            file=uploaded_file,
            file_type=file_type,
        )

        return Response(
            {
                "message": "Attachment uploaded successfully",
                "file_url": attachment.file.url,
                "file_type": attachment.file_type,
            },
            status=201,
        )


class VisitAttachmentDownloadAPI(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, file_id):
        attachment = get_object_or_404(VisitAttachment, id=file_id)

        # ✅ Force browser to download
        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.file.name.split("/")[-1],
        )
