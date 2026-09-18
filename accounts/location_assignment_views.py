"""Admin employee location assignment APIs (village-based operational territory)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from accounts.location_assignments import (
    LocationAssignmentValidationError,
    annotate_assignment_counts,
    assignment_previews_for_employees,
    assignment_rows_for_employee,
    assignment_summary_from_rows,
    employee_summary_payload,
    expand_village_ids,
    extract_village_ids_from_payload,
    field_employee_queryset,
    filter_employees_for_assignment_list,
    legacy_incomplete_assignment_count,
    replace_employee_location_assignments,
    village_payload_from_rows,
)
from accounts.models import EmployeeProfile
from utils.permissions import IsStaffAdmin
from utils.response import error_response, not_found_response, success_response


@extend_schema(
    tags=["Employee Location Assignments"],
    summary="Admin — list employee location assignment summaries",
    parameters=[
        OpenApiParameter("employee", OpenApiTypes.INT, description="EmployeeProfile id"),
        OpenApiParameter("district", OpenApiTypes.INT, description="Legacy district id filter"),
        OpenApiParameter("taluk", OpenApiTypes.INT, description="Legacy taluk id filter"),
        OpenApiParameter("village", OpenApiTypes.INT, description="Village id filter"),
        OpenApiParameter("search", OpenApiTypes.STR, description="Employee id/name search"),
        OpenApiParameter("page", OpenApiTypes.INT),
        OpenApiParameter("page_size", OpenApiTypes.INT),
    ],
)
class AdminEmployeeLocationAssignmentListAPI(APIView):
    """
    GET /api/v1/admin/employee-location-assignments/

    Operational village-level territory summaries for Admin.
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

        page_profiles = list(page)
        previews = assignment_previews_for_employees([p.id for p in page_profiles])

        results = []
        for profile in page_profiles:
            results.append(
                {
                    "employee": employee_summary_payload(profile),
                    "location_assignment_summary": {
                        "village_count": profile.location_village_count,
                        "district_count": profile.location_district_count,
                        "taluk_count": profile.location_taluk_count,
                    },
                    "location_assignment_preview": previews.get(
                        profile.id,
                        {"villages": [], "districts": [], "taluks": []},
                    ),
                }
            )

        paginated = paginator.get_paginated_response(results).data
        return success_response(data=paginated)


@extend_schema(
    tags=["Employee Location Assignments"],
    summary="Admin — employee location assignment detail",
)
class AdminEmployeeLocationAssignmentDetailAPI(APIView):
    """
    GET /api/v1/admin/employees/{pk}/location-assignments/
    PUT /api/v1/admin/employees/{pk}/location-assignments/
    PATCH /api/v1/admin/employees/{pk}/location-assignments/

    Preferred write payload: {"village_ids": [1, 2, 3]}
    Legacy assignments wrapper is still accepted; district/taluk are ignored.
    """

    permission_classes = [IsStaffAdmin]

    def _get_field_employee(self, pk: int) -> EmployeeProfile | None:
        return (
            field_employee_queryset()
            .filter(pk=pk)
            .first()
        )

    def _detail_payload(self, employee: EmployeeProfile, rows=None) -> dict:
        if rows is None:
            rows = list(assignment_rows_for_employee(employee.id))
        villages = village_payload_from_rows(rows)
        return {
            "employee": employee_summary_payload(employee),
            "location_assignment_summary": assignment_summary_from_rows(rows),
            "legacy_incomplete_count": legacy_incomplete_assignment_count(
                employee.id
            ),
            "villages": villages,
            "assignments": villages,
        }

    def get(self, request, pk: int):
        employee = self._get_field_employee(pk)
        if not employee:
            return not_found_response("Employee not found.")
        return success_response(data=self._detail_payload(employee))

    def put(self, request, pk: int):
        return self._replace(request, pk)

    def patch(self, request, pk: int):
        return self._replace(request, pk)

    def _replace(self, request, pk: int):
        employee = self._get_field_employee(pk)
        if not employee:
            return not_found_response("Employee not found.")

        try:
            village_ids = extract_village_ids_from_payload(
                request.data if isinstance(request.data, dict) else {}
            )
            expand_village_ids(village_ids)
            rows = replace_employee_location_assignments(
                employee=employee,
                village_ids=village_ids,
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
            data=self._detail_payload(employee, rows=rows),
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
