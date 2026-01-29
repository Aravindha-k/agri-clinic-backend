from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .serializers import (
    EmployeeCreateSerializer,
    MeSerializer,
    AdminResetPasswordSerializer,
)
from django.db import IntegrityError, transaction
from .models import EmployeeProfile
from django.contrib.auth.models import User
from .utils import generate_employee_id


class CreateEmployeeAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return Response(
                {"detail": "Admin only"},
                status=403,
            )

        username = request.data.get("username", "").strip()
        password = request.data.get("password")
        phone = request.data.get("phone")

        if not username or not password:
            return Response(
                {"detail": "Username and password required"},
                status=400,
            )

        # ✅ Exact match check only (case-sensitive)
        if User.objects.filter(username=username).exists():
            return Response(
                {"detail": "Username already exists"},
                status=400,
            )

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    password=password,
                )

                employee_id = generate_employee_id()

                EmployeeProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    phone=phone,
                )

        except IntegrityError as e:
            return Response(
                {
                    "detail": "Employee creation failed",
                    "error": str(e),
                },
                status=400,
            )

        return Response(
            {
                "message": "Employee created successfully",
                "employee_id": employee_id,
            },
            status=status.HTTP_201_CREATED,
        )


class MeAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = MeSerializer(request.user)
        return Response(serializer.data)


class AdminResetPasswordAPI(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"message": "Password reset successfully"},
            status=status.HTTP_200_OK,
        )


class EmployeeListAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response(
                {"detail": "Admin only"},
                status=403,
            )

        employees = (
            EmployeeProfile.objects.select_related("user").all().order_by("employee_id")
        )

        data = []
        for emp in employees:
            data.append(
                {
                    "id": emp.id,  # ✅ REQUIRED for Edit/Delete
                    "user_id": emp.user.id,
                    "employee_id": emp.employee_id,
                    "username": emp.user.username,
                    "phone": emp.phone,
                    "is_active_employee": emp.is_active_employee,
                    "can_login": emp.user.is_active,
                }
            )

        return Response(data)


class ToggleEmployeeStatusAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, employee_id):
        if not request.user.is_staff:
            return Response(
                {"detail": "Admin only"},
                status=403,
            )

        employee = get_object_or_404(EmployeeProfile, employee_id=employee_id)

        # 🔁 Toggle both flags
        employee.is_active_employee = not employee.is_active_employee
        employee.user.is_active = employee.is_active_employee

        employee.user.save()
        employee.save()

        return Response(
            {
                "employee_id": employee.employee_id,
                "is_active_employee": employee.is_active_employee,
            },
            status=200,
        )


class AdminEmployeeUpdateDeleteAPI(APIView):
    permission_classes = [IsAdminUser]

    # ✅ UPDATE EMPLOYEE
    def patch(self, request, emp_id):
        try:
            emp = EmployeeProfile.objects.get(id=emp_id)
        except EmployeeProfile.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)

        username = request.data.get("username")
        phone = request.data.get("phone")

        # ✅ Update fields
        if username:
            emp.user.username = username
            emp.user.save()

        if phone:
            if not phone.isdigit() or len(phone) != 10:
                return Response(
                    {"error": "Phone must be exactly 10 digits"},
                    status=400,
                )
            emp.phone = phone
            emp.save()

        return Response({"message": "Employee updated successfully"})

    # ✅ DELETE EMPLOYEE
    def delete(self, request, emp_id):
        try:
            emp = EmployeeProfile.objects.get(id=emp_id)
        except EmployeeProfile.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)

        emp.user.delete()  # Deletes profile also (CASCADE)

        return Response({"message": "Employee deleted successfully"})
