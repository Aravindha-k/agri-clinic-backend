"""Celery tasks for duty tracking."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="tracking.tasks.expire_overdue_duties_task")
def expire_overdue_duties_task() -> int:
    """Periodic auto-complete for DutySessions past the 9-hour limit."""
    from tracking.duty_expiry import expire_overdue_duties

    count = expire_overdue_duties(trigger="celery")
    logger.info("expire_overdue_duties_task closed=%s", count)
    return count
