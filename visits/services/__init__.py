"""Visit domain services.

Canonical create path: ``visits.services.field_visit_service``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from django.contrib.auth.models import User
from django.db import transaction

from visits.models import Visit
from visits.services.field_visit_service import (  # noqa: F401
    MAX_BULK_VISITS,
    FieldVisitServiceError,
    FieldVisitSubmitResult,
    bulk_submit_field_visits,
    ensure_visit_route_point,
    submit_field_visit,
    submit_field_visit_validated,
)
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE, visit_has_submitted_details

logger = logging.getLogger(__name__)


class VisitServiceError(Exception):
    """Raised for visit domain business rule violations."""


@transaction.atomic
def create_visit(
    *,
    employee: User,
    farmer_id: int,
    crop_id: int,
    latitude: float,
    longitude: float,
    farmer_name: Optional[str] = None,
    farmer_phone: Optional[str] = None,
    village_id: Optional[int] = None,
    district_id: Optional[int] = None,
    visit_date: Optional[date] = None,
    address: str = "",
    land_name: Optional[str] = None,
    land_area: Optional[float] = None,
    crop_stage: str = "",
    variety: str = "",
    season: str = "",
    crop_health: str = "",
    pest_issue: bool = False,
    disease_issue: bool = False,
    weed_condition: str = "",
    notes: str = "",
    fertilizer_advice: str = "",
    pesticide_advice: str = "",
    irrigation_advice: str = "",
    general_advice: str = "",
    follow_up_required: bool = False,
    next_visit_date: Optional[date] = None,
    **kwargs: Any,
) -> Visit:
    """
    DEPRECATED thin wrapper → canonical ``submit_field_visit``.

    Prefer FieldVisitSubmitSerializer / submit_field_visit directly.
    """
    raw = {
        "farmer_id": farmer_id,
        "crop_id": crop_id,
        "latitude": latitude,
        "longitude": longitude,
        "farmer_name": farmer_name,
        "farmer_phone": farmer_phone,
        "village_id": village_id,
        "district": district_id,
        "visit_date": visit_date,
        "address": address,
        "land_name": land_name,
        "land_area": land_area,
        "crop_stage": crop_stage,
        "variety": variety,
        "season": season,
        "crop_health": crop_health,
        "pest_issue": pest_issue,
        "disease_issue": disease_issue,
        "weed_condition": weed_condition,
        "notes": notes,
        "problem_description": notes or "Legacy create_visit",
        "fertilizer_advice": fertilizer_advice,
        "pesticide_advice": pesticide_advice,
        "irrigation_advice": irrigation_advice,
        "general_advice": general_advice,
        "follow_up_required": follow_up_required,
        "next_visit_date": next_visit_date,
        **kwargs,
    }
    # Drop Nones so serializer optional fields behave.
    raw = {k: v for k, v in raw.items() if v is not None and v != ""}
    try:
        result = submit_field_visit(employee=employee, raw_data=raw, request=None)
    except Exception as exc:
        raise VisitServiceError(str(exc)) from exc
    visit = result.visit
    if not visit_has_submitted_details(visit):
        raise VisitServiceError(SUBMIT_VISIT_REQUIRED_MESSAGE)
    try:
        from visits.tasks import notify_visit_created

        notify_visit_created.delay(visit.pk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not enqueue notify_visit_created task: %s", exc)
    return visit


@transaction.atomic
def update_visit(*, visit: Visit, updated_by: User, **kwargs: Any) -> Visit:
    """Partial update of a visit. Protected fields are stripped."""
    _FORBIDDEN = {
        "local_sync_id",
        "duty_session",
        "duty_session_id",
        "workday",
        "workday_id",
        "employee",
        "employee_id",
    }
    _ALLOWED_FIELDS = {
        "farmer_name",
        "farmer_phone",
        "village_id",
        "district_id",
        "visit_date",
        "latitude",
        "longitude",
        "address",
        "land_name",
        "land_area",
        "crop_id",
        "crop_stage",
        "variety",
        "season",
        "crop_health",
        "pest_issue",
        "disease_issue",
        "weed_condition",
        "notes",
        "fertilizer_advice",
        "pesticide_advice",
        "irrigation_advice",
        "general_advice",
        "follow_up_required",
        "next_visit_date",
        "status",
        "observation",
        "recommendation",
        "action_taken",
        "farmer_id",
    }

    update_fields = []
    for field, value in kwargs.items():
        if field in _FORBIDDEN:
            continue
        if field in _ALLOWED_FIELDS:
            setattr(visit, field, value)
            update_fields.append(field)

    if update_fields:
        update_fields.append("updated_at")
        visit.save(update_fields=update_fields)
        ensure_visit_route_point(visit)

    logger.info("Visit updated: id=%s by user_id=%s", visit.pk, updated_by.pk)
    return visit


def delete_visit(*, visit: Visit, deleted_by: User) -> None:
    """Hard-delete a visit (admin only)."""
    pk = visit.pk
    visit.delete()
    logger.info("Visit deleted: id=%s by user_id=%s", pk, deleted_by.pk)
