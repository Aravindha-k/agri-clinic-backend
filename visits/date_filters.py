"""Date-range filters for visit list APIs (mobile date_filter query param)."""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone


def visit_date_filter_bounds(date_filter: str | None) -> tuple[date, date] | None:
    """
    Map date_filter values to inclusive [start, end] local dates.

    Supported: today, week (Mon–today), month (1st–today).
    """
    if not date_filter:
        return None

    key = str(date_filter).strip().lower()
    if key in {"", "all"}:
        return None

    today = timezone.localdate()

    if key == "today":
        return today, today
    if key == "week":
        week_start = today - timedelta(days=today.weekday())
        return week_start, today
    if key == "month":
        return today.replace(day=1), today

    return None


def apply_visit_date_filter(qs: QuerySet, date_filter: str | None) -> QuerySet:
    """Filter visits by visit_date, falling back to created_at date when visit_date is null."""
    bounds = visit_date_filter_bounds(date_filter)
    if not bounds:
        return qs

    start, end = bounds
    return qs.filter(
        Q(visit_date__gte=start, visit_date__lte=end)
        | Q(
            visit_date__isnull=True,
            created_at__date__gte=start,
            created_at__date__lte=end,
        )
    )
