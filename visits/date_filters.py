"""Date-range filters for visit list APIs (mobile date_filter query param)."""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError


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


def parse_optional_iso_date(value, *, field_name: str) -> date | None:
    """Parse YYYY-MM-DD; blank/None → None; invalid → ValidationError (HTTP 400)."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError(
            {field_name: "Invalid date. Use YYYY-MM-DD."},
            code="invalid",
        ) from exc


def apply_visit_date_range(
    qs: QuerySet,
    start: date | None = None,
    end: date | None = None,
) -> QuerySet:
    """
    Filter visits by inclusive local calendar dates.

    Canonical field: visit_date (DateField).
    Fallback when visit_date is null: created_at date in the active timezone
    (settings.TIME_ZONE = Asia/Kolkata).
    """
    if start is None and end is None:
        return qs

    if start is not None and end is not None and start > end:
        raise ValidationError(
            {"start_date": "start_date must be on or before end_date."},
            code="invalid",
        )

    primary = Q()
    fallback = Q(visit_date__isnull=True)
    if start is not None:
        primary &= Q(visit_date__gte=start)
        fallback &= Q(created_at__date__gte=start)
    if end is not None:
        primary &= Q(visit_date__lte=end)
        fallback &= Q(created_at__date__lte=end)

    return qs.filter(primary | fallback)


def apply_visit_date_filter(qs: QuerySet, date_filter: str | None) -> QuerySet:
    """Filter visits by visit_date, falling back to created_at date when visit_date is null."""
    bounds = visit_date_filter_bounds(date_filter)
    if not bounds:
        return qs

    start, end = bounds
    return apply_visit_date_range(qs, start, end)


def parse_report_date_params(params) -> tuple[date | None, date | None]:
    """
    Accept from/to (reports UI) or start_date/end_date (existing report APIs).
    """
    start_raw = params.get("from") or params.get("start_date")
    end_raw = params.get("to") or params.get("end_date")
    start_field = "from" if params.get("from") else "start_date"
    end_field = "to" if params.get("to") else "end_date"
    start = parse_optional_iso_date(start_raw, field_name=start_field)
    end = parse_optional_iso_date(end_raw, field_name=end_field)
    return start, end
