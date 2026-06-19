"""Admin employee day report and visit listing APIs."""

from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from tracking.admin_duty_views import _resolve_target_date
from tracking.employee_report import (
    EmployeeNotFoundError,
    build_employee_day_report,
    build_employee_day_summary,
    build_employee_visits_for_date,
    resolve_employee_profile,
)
from tracking.workday_utils import expire_old_workdays
from utils.response import error_response, not_found_response, success_response
from utils.schema import SIMPLE_SUCCESS, error_schema


def _resolve_employee_or_404(employee_ref: int):
    try:
        return resolve_employee_profile(employee_ref)
    except EmployeeNotFoundError:
        return None


@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee visits by date",
    parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="YYYY-MM-DD")],
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeVisitsByDateAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, employee_id):
        expire_old_workdays()
        emp = _resolve_employee_or_404(employee_id)
        if not emp:
            return not_found_response("Employee not found")

        target_date, err = _resolve_target_date(request)
        if err:
            return err

        data = build_employee_visits_for_date(
            user_id=emp.user_id,
            target_date=target_date,
            request=request,
        )
        data["employee"] = {
            "profile_id": emp.pk,
            "user_id": emp.user_id,
            "employee_id": emp.employee_id,
        }
        return success_response(data=data, message="Employee visits loaded")


@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee day summary",
    parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="YYYY-MM-DD")],
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeDaySummaryAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, employee_id):
        expire_old_workdays()
        emp = _resolve_employee_or_404(employee_id)
        if not emp:
            return not_found_response("Employee not found")

        target_date, err = _resolve_target_date(request)
        if err:
            return err

        data = build_employee_day_summary(
            emp=emp,
            target_date=target_date,
            request=request,
        )
        return success_response(data=data, message="Day summary loaded")


@extend_schema(
    tags=["Tracking"],
    summary="Admin: employee day report",
    parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="YYYY-MM-DD")],
    responses={200: SIMPLE_SUCCESS, 404: error_schema("EmployeeNotFound")},
)
class AdminEmployeeDayReportAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, employee_id):
        expire_old_workdays()
        emp = _resolve_employee_or_404(employee_id)
        if not emp:
            return not_found_response("Employee not found")

        target_date, err = _resolve_target_date(request)
        if err:
            return err

        data = build_employee_day_report(
            emp=emp,
            target_date=target_date,
            request=request,
        )
        return success_response(data=data, message="Day report loaded")
