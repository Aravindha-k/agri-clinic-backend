"""Farmer list cache helpers."""

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

FARMERS_LIST_CACHE_KEY = "farmers:list:v1"


def invalidate_farmers_list_cache() -> None:
    """Clear cached farmer list payloads after visit mutations."""
    try:
        cache.delete(FARMERS_LIST_CACHE_KEY)
    except Exception:
        logger.debug("farmers list cache invalidation skipped", exc_info=True)
