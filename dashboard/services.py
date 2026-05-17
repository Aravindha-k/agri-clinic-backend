"""
dashboard/services.py
──────────────────────
Dashboard business logic + Redis caching layer.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from django.core.cache import cache

from . import selectors

logger = logging.getLogger(__name__)

# Cache TTLs (seconds)
STATS_TTL = 60  # 1 minute – near real-time
TRENDS_TTL = 5 * 60  # 5 minutes
PERFORMANCE_TTL = 5 * 60


def get_stats() -> Dict:
    """Return dashboard stats, served from Redis cache when available."""
    cache_key = "dashboard:stats"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = selectors.get_dashboard_stats()
    cache.set(cache_key, data, timeout=STATS_TTL)
    return data


def invalidate_stats_cache() -> None:
    """Backward-compatible alias — clears all dashboard KPI caches."""
    invalidate_dashboard_caches()


def invalidate_dashboard_caches() -> None:
    """Invalidate cached dashboard aggregates after visits or tracking changes."""
    keys = [
        "dashboard:stats",
        "dashboard:summary",
        "dashboard:employee-performance",
        "dashboard:employee_performance",
        "dashboard:heatmap",
        "dashboard:visit-trends",
    ]
    for key in keys:
        cache.delete(key)
    for days in (7, 14, 30, 60, 90, 365):
        cache.delete(f"dashboard:visit_trends:{days}")
        cache.delete(f"dashboard:emp_perf:{days}")
        cache.delete(f"dashboard:employee-performance:{days}")
    for top_n in (10, 20, 50, 100):
        cache.delete(f"dashboard:village_heatmap:{top_n}")
    logger.debug("Dashboard caches invalidated")


def get_visit_trends(days: int = 30) -> List[Dict]:
    cache_key = f"dashboard:visit_trends:{days}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = selectors.get_visit_trends(days=days)
    cache.set(cache_key, data, timeout=TRENDS_TTL)
    return data


def get_employee_performance(days: int = 30) -> List[Dict]:
    cache_key = f"dashboard:emp_perf:{days}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = selectors.get_employee_performance(days=days)
    cache.set(cache_key, data, timeout=PERFORMANCE_TTL)
    return data


def get_village_heatmap(top_n: int = 20) -> List[Dict]:
    cache_key = f"dashboard:village_heatmap:{top_n}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = selectors.get_village_heatmap(top_n=top_n)
    cache.set(cache_key, data, timeout=TRENDS_TTL)
    return data
