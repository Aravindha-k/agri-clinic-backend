"""Celery tasks for duty tracking."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="tracking.tasks.expire_overdue_duties_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def expire_overdue_duties_task(self) -> int:
    """
    Periodic auto-complete for DutySessions past the 9-hour limit.

    Idempotent: complete_duty_as_auto_expired is safe under concurrent runs;
    does not invent WORKDAY_END GPS coordinates.
    """
    from tracking.duty_expiry import expire_overdue_duties

    try:
        count = expire_overdue_duties(trigger="celery")
        logger.info(
            "event=duty_auto_expiry_task closed=%s trigger=celery",
            count,
        )
        return count
    except Exception as exc:
        logger.exception("event=duty_auto_expiry_task_failed")
        raise self.retry(exc=exc)
