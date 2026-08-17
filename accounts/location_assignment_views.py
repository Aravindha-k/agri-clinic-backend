"""Admin-only employee location assignment reference APIs."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from accounts.location_assignments import (
    LocationAssignmentValidationError,
    annotate_assignment_counts,
    assignment_rows_for_employee,
    assignment_summary_from_rows,
    employee_summary_payload,
    expand_assignment_groups,
    field_employee_queryset,
    filter_employees_for_assignment_list,
    group_assignments_for_response,
    replace_employee_location_assignments,
)
from accounts.models import EmployeeProfile
from utils.permissions import IsStaffAdmin
from utils.response import error_response, not_found_response, success_response


class AssignmentGroupSerializerMixin:
    """Shared validation for hierarchy assignment payload."""

    @staticmethod
    def validate_payload(data: dict) -> list[dict]:
        groups = data.get("assignments")
        if groups is None:
            raise LocationAssignmentValidationError(
                {"assignments": "This field is required."}
            )
        if not isinstance(groups, list):
            raise LocationAssignmentValidationError(
                {"assignments": "Must be a list of assignment groups."}
            )
        return groups


@extend_schema(
    tags=["Employee Location Assignments"],
    summary="Admin — list employee location assignment summaries",
    parameters=[
        OpenApiParameter("employee", OpenApiTypes.INT, description="EmployeeProfile id"),
        OpenApiParameter("district", OpenApiTypes.INT, description="District id filter"),
        OpenApiParameter("taluk", OpenApiTypes.INT, description="Taluk id filter"),
        OpenApiParameter("village", OpenApiTypes.INT, description="Village id filter"),
        OpenApiParameter("search", OpenApiTypes.STR, description="Employee id/name search"),
        OpenApiParameter("page", OpenApiTypes.INT),
        OpenApiParameter("page_size", OpenApiTypes.INT),
    ],
)
class AdminEmployeeLocationAssignmentListAPI(APIView):
    """
    GET /api/v1/admin/employee-location-assignments/

    Administrative reference metadata only. Must not be used for authorization
    or operational scoping.
    """

    permission_classes = [IsStaffAdmin]

    def get(self, request):
        qs = field_employee_queryset()
        qs = filter_employees_for_assignment_list(
            qs,
            employee_id=_int_param(request, "employee"),
            district_id=_int_param(request, "district"),
            taluk_id=_int_param(request, "taluk"),
            village_id=_int_param(request, "village"),
            search=(request.query_params.get("search") or "").strip() or None,
        )
        qs = annotate_assignment_counts(qs)

        paginator = PageNumberPagination()
        paginator.page_size = min(int(request.query_params.get("page_size", 20)), 100)
        page = paginator.paginate_queryset(qs, request)

        results = []
        for profile in page:
            results.append(
                {
                    "employee": employee_summary_payload(profile),
                    "location_assignment_summary": {
                        "district_count": profile.location_district_count,
                        "taluk_count": profile.location_taluk_count,
                        "village_count": profile.location_village_count,
                    },
                }
            )

        paginated = paginator.get_paginated_response(results).data
        return success_response(data=paginated)


@extend_schema(
    tags=["Employee Location Assignments"],
    summary="Admin — employee location assignment detail",
)
class AdminEmployeeLocationAssignmentDetailAPI(APIView, AssignmentGroupSerializerMixin):
    """
    GET /api/v1/admin/employees/{pk}/location-assignments/
    PUT /api/v1/admin/employees/{pk}/location-assignments/
    PATCH /api/v1/admin/employees/{pk}/location-assignments/
    """

    permission_classes = [IsStaffAdmin]

    def _get_field_employee(self, pk: int) -> EmployeeProfile | None:
        return (
            field_employee_queryset()
            .filter(pk=pk)
            .first()
        )

    def get(self, request, pk: int):
        employee = self._get_field_employee(pk)
        if not employee:
            return not_found_response("Employee not found.")
        rows = list(assignment_rows_for_employee(employee.id))
        return success_response(
            data={
                "employee": employee_summary_payload(employee),
                "location_assignment_summary": assignment_summary_from_rows(rows),
                "assignments": group_assignments_for_response(rows),
            }
        )

    def put(self, request, pk: int):
        return self._replace(request, pk)

    def patch(self, request, pk: int):
        return self._replace(request, pk)

    def _replace(self, request, pk: int):
        employee = self._get_field_employee(pk)
        if not employee:
            return not_found_response("Employee not found.")

        try:
            groups = self.validate_payload(request.data)
            # Validate before mutating
            expand_assignment_groups(groups)
            rows = replace_employee_location_assignments(
                employee=employee,
                assignment_groups=groups,
                actor=request.user,
            )
        except LocationAssignmentValidationError as exc:
            return error_response(
                message="Invalid location assignment payload.",
                errors=exc.detail,
                code="VALIDATION_ERROR",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return success_response(
            data={
                "employee": employee_summary_payload(employee),
                "location_assignment_summary": assignment_summary_from_rows(rows),
                "assignments": group_assignments_for_response(rows),
            },
            message="Location assignments updated.",
        )


def _int_param(request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
