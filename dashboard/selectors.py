"""
dashboard/selectors.py
───────────────────────
Read-only query functions for the dashboard domain.
All heavy aggregations go through these functions so views stay thin.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List

from django.db.models import Count, Q

logger = logging.getLogger(__name__)


def get_dashboard_stats() -> Dict:
    """
    Core stats: total farmers, total visits, today visits, active employees.
    Executed against PostgreSQL – cached by the service layer.
    """
    from visits.models import Visit
    from masters.models import Farmer
    from accounts.models import EmployeeProfile

    today = date.today()

    return {
        "total_farmers": Farmer.objects.filter(is_active=True).count(),
        "total_visits": Visit.objects.count(),
        "today_visits": Visit.objects.filter(visit_date=today).count(),
        "active_employees": EmployeeProfile.objects.filter(
            is_active_employee=True
        ).count(),
    }


def get_visit_trends(days: int = 30) -> List[Dict]:
    """Daily visit count for the last `days` days."""
    from visits.models import Visit

    date_from = date.today() - timedelta(days=days - 1)
    return list(
        Visit.objects.filter(visit_date__gte=date_from)
        .values("visit_date")
        .annotate(count=Count("id"))
        .order_by("visit_date")
        .values("visit_date", "count")
    )


def get_employee_performance(days: int = 30) -> List[Dict]:
    """Visit count per employee for the last `days` days."""
    from visits.models import Visit

    date_from = date.today() - timedelta(days=days - 1)
    return list(
        Visit.objects.filter(visit_date__gte=date_from)
        .values(
            "employee__id",
            "employee__username",
            "employee__employee_profile__employee_id",
        )
        .annotate(visit_count=Count("id"))
        .order_by("-visit_count")
    )


def get_village_heatmap(top_n: int = 20) -> List[Dict]:
    """Top N villages by visit count."""
    from visits.models import Visit

    return list(
        Visit.objects.filter(village__isnull=False)
        .values("village__id", "village__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:top_n]
    )
