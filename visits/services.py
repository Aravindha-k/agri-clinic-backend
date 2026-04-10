"""
visits/services.py
───────────────────
Business logic for visit management.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from django.contrib.auth.models import User
from django.db import transaction

from .models import Visit

logger = logging.getLogger(__name__)


class VisitServiceError(Exception):
    """Raised for visit domain business rule violations."""


# ──────────────────────────────────────────────────────────────
# Visit creation
# ──────────────────────────────────────────────────────────────


@transaction.atomic
def create_visit(
    *,
    employee: User,
    farmer_name: Optional[str] = None,
    farmer_phone: Optional[str] = None,
    village_id: Optional[int] = None,
    district_id: Optional[int] = None,
    visit_date: Optional[date] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    address: str = "",
    land_name: Optional[str] = None,
    land_area: Optional[float] = None,
    crop_id: Optional[int] = None,
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
) -> Visit:
    """
    Create a new visit record.

    Schedules a post-creation notification task asynchronously.
    """
    if visit_date is None:
        visit_date = date.today()

    visit = Visit.objects.create(
        employee=employee,
        farmer_name=farmer_name,
        farmer_phone=farmer_phone,
        village_id=village_id,
        district_id=district_id,
        visit_date=visit_date,
        latitude=latitude,
        longitude=longitude,
        address=address,
        land_name=land_name,
        land_area=land_area,
        crop_id=crop_id,
        crop_stage=crop_stage,
        variety=variety,
        season=season,
        crop_health=crop_health,
        pest_issue=pest_issue,
        disease_issue=disease_issue,
        weed_condition=weed_condition,
        notes=notes,
        fertilizer_advice=fertilizer_advice,
        pesticide_advice=pesticide_advice,
        irrigation_advice=irrigation_advice,
        general_advice=general_advice,
        follow_up_required=follow_up_required,
        next_visit_date=next_visit_date,
        status="completed",
    )

    # Trigger async notification (import here to avoid circular imports)
    try:
        from visits.tasks import notify_visit_created

        notify_visit_created.delay(visit.pk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not enqueue notify_visit_created task: %s", exc)

    logger.info(
        "Visit created: id=%s employee=%s farmer=%s",
        visit.pk,
        employee.username,
        farmer_phone or farmer_name,
    )
    return visit


# ──────────────────────────────────────────────────────────────
# Visit update
# ──────────────────────────────────────────────────────────────


@transaction.atomic
def update_visit(*, visit: Visit, updated_by: User, **kwargs: Any) -> Visit:
    """
    Partial update of a visit.
    Only fields included in kwargs are updated.
    """
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
    }

    update_fields = []
    for field, value in kwargs.items():
        if field in _ALLOWED_FIELDS:
            setattr(visit, field, value)
            update_fields.append(field)

    if update_fields:
        update_fields.append("updated_at")
        visit.save(update_fields=update_fields)

    logger.info("Visit updated: id=%s by user_id=%s", visit.pk, updated_by.pk)
    return visit


def delete_visit(*, visit: Visit, deleted_by: User) -> None:
    """Hard-delete a visit (admin only)."""
    pk = visit.pk
    visit.delete()
    logger.info("Visit deleted: id=%s by user_id=%s", pk, deleted_by.pk)
