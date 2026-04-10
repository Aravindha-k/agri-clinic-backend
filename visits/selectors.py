"""
visits/selectors.py
────────────────────
Pure read / query functions for the visits domain.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from django.contrib.auth.models import User
from django.db.models import Count, F, Q, QuerySet

from .models import Visit

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Core visit queries
# ──────────────────────────────────────────────────────────────


def get_visits(
    *,
    employee: Optional[User] = None,
    visit_date: Optional[date] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    village_id: Optional[int] = None,
    district_id: Optional[int] = None,
    farmer_phone: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet:
    """Full-featured visit queryset with all filters applied."""
    qs = Visit.objects.select_related(
        "employee",
        "employee__employee_profile",
        "village",
        "district",
        "crop",
    ).order_by("-visit_date", "-created_at")

    if employee:
        qs = qs.filter(employee=employee)
    if visit_date:
        qs = qs.filter(visit_date=visit_date)
    if date_from:
        qs = qs.filter(visit_date__gte=date_from)
    if date_to:
        qs = qs.filter(visit_date__lte=date_to)
    if village_id:
        qs = qs.filter(village_id=village_id)
    if district_id:
        qs = qs.filter(district_id=district_id)
    if farmer_phone:
        qs = qs.filter(farmer_phone=farmer_phone)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(farmer_name__icontains=search)
            | Q(farmer_phone__icontains=search)
            | Q(notes__icontains=search)
            | Q(village__name__icontains=search)
        )

    return qs


def get_visit_by_id(visit_id: int) -> Optional[Visit]:
    return (
        Visit.objects.select_related(
            "employee", "employee__employee_profile", "village", "district", "crop"
        )
        .filter(pk=visit_id)
        .first()
    )


def get_today_visits(employee: Optional[User] = None) -> QuerySet:
    qs = Visit.objects.filter(visit_date=date.today())
    if employee:
        qs = qs.filter(employee=employee)
    return qs


# ──────────────────────────────────────────────────────────────
# Aggregates / analytics
# ──────────────────────────────────────────────────────────────


def get_total_visit_count() -> int:
    return Visit.objects.count()


def get_today_visit_count(employee: Optional[User] = None) -> int:
    qs = Visit.objects.filter(visit_date=date.today())
    if employee:
        qs = qs.filter(employee=employee)
    return qs.count()


def get_visit_trends(*, date_from: date, date_to: date) -> QuerySet:
    """Daily visit count between two dates."""
    return (
        Visit.objects.filter(visit_date__gte=date_from, visit_date__lte=date_to)
        .values("visit_date")
        .annotate(count=Count("id"))
        .order_by("visit_date")
    )


def get_employee_performance(*, date_from: date, date_to: date) -> QuerySet:
    """Visit count per employee in a date range."""
    return (
        Visit.objects.filter(visit_date__gte=date_from, visit_date__lte=date_to)
        .values("employee__username", "employee__employee_profile__employee_id")
        .annotate(visit_count=Count("id"))
        .order_by("-visit_count")
    )


def get_farmer_visit_history(farmer_phone: str) -> QuerySet:
    return (
        Visit.objects.select_related("employee", "village", "district", "crop")
        .filter(farmer_phone=farmer_phone)
        .order_by("-visit_date")
    )
