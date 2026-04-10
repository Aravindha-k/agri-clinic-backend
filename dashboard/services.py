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
    """Call this whenever a visit is created/deleted to keep stats fresh."""
    cache.delete("dashboard:stats")


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
