"""Invalidate caches that embed employee profile photos."""

import logging

logger = logging.getLogger(__name__)


def invalidate_employee_photo_caches() -> None:
    """Clear caches that embed employee profile photos."""
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception as exc:
        logger.debug("dashboard cache invalidate skipped: %s", exc)

    try:
        from visits.views import _invalidate_visit_caches

        _invalidate_visit_caches()
    except Exception as exc:
        logger.debug("visit cache invalidate skipped: %s", exc)
