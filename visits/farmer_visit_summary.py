"""Farmer revisit summary and visit history for mobile + web APIs."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models import Q, QuerySet

from masters.models import Farmer
from visits.field_notes import (
    resolved_field_notes,
    resolved_recommendation,
    stored_observation,
)
from visits.models import Visit
from visits.querysets import submitted_visits_with_relations
from visits.submitted import submitted_visits_qs
from visits.visit_response import build_field_visit_problem_block, crop_display_name


def farmer_visits_qs(farmer: Farmer, *, employee: User | None = None) -> QuerySet:
    """Submitted visits linked to a farmer (FK, phone, or name match)."""
    qs = submitted_visits_qs().filter(
        Q(farmer=farmer)
        | Q(farmer_phone=farmer.phone)
        | Q(farmer_name__iexact=farmer.name)
    )
    if employee is not None:
        qs = qs.filter(employee=employee)
    return (
        submitted_visits_with_relations()
        .filter(pk__in=qs.values("pk"))
        .order_by("-visit_date", "-created_at", "-id")
    )


def _visit_history_row(visit: Visit) -> dict:
    problem = build_field_visit_problem_block(visit) or {}
    return {
        "id": visit.id,
        "visit_date": str(visit.visit_date) if visit.visit_date else None,
        "created_at": visit.created_at.isoformat() if visit.created_at else None,
        "crop_id": visit.crop_id,
        "crop_name": crop_display_name(visit),
        "problem_category": problem.get("problem_category"),
        "problem_item": problem.get("problem_master"),
        "problem_master": problem.get("problem_master"),
        "problem_description": visit.problem_description or visit.problem_seen or "",
        "recommendation": resolved_recommendation(visit) or None,
        "observation": stored_observation(visit) or resolved_field_notes(visit) or None,
        "action_taken": visit.action_taken or None,
        "latitude": visit.latitude,
        "longitude": visit.longitude,
        "media_count": visit.media_files.count(),
    }


def build_farmer_revisit_summary(
    farmer: Farmer,
    *,
    employee: User | None = None,
) -> dict:
    """Latest visit context for revisit flow (per employee when scoped)."""
    qs = farmer_visits_qs(farmer, employee=employee)
    visit_count = qs.count()
    latest = qs.first()
    if not latest:
        return {
            "last_visit_date": None,
            "visit_count": 0,
            "latest_crop": None,
            "latest_crop_id": None,
            "latest_problem": None,
            "latest_problem_item": None,
            "latest_recommendation": None,
            "latest_observation": None,
            "latest_action_taken": None,
        }

    problem = build_field_visit_problem_block(latest) or {}
    return {
        "last_visit_date": str(latest.visit_date) if latest.visit_date else None,
        "visit_count": visit_count,
        "latest_crop": crop_display_name(latest) or None,
        "latest_crop_id": latest.crop_id,
        "latest_problem": problem.get("problem_description")
        or latest.problem_description
        or latest.problem_seen
        or None,
        "latest_problem_item": problem.get("problem_master"),
        "latest_recommendation": resolved_recommendation(latest) or None,
        "latest_observation": stored_observation(latest)
        or resolved_field_notes(latest)
        or None,
        "latest_action_taken": latest.action_taken or None,
    }


def build_farmer_visit_history(
    farmer: Farmer,
    *,
    employee: User | None = None,
    limit: int = 20,
) -> list[dict]:
    qs = farmer_visits_qs(farmer, employee=employee).prefetch_related("media_files")
    return [_visit_history_row(v) for v in qs[:limit]]


def count_farmers_covered_today(employee: User, *, today) -> int:
    return (
        submitted_visits_qs()
        .filter(employee=employee, visit_date=today, farmer_id__isnull=False)
        .values("farmer_id")
        .distinct()
        .count()
    )
