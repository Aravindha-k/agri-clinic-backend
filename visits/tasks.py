"""
visits/tasks.py
────────────────
Celery tasks for the visits domain.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def notify_visit_created(self, visit_id: int) -> None:
    """
    Create an in-app notification when a new visit is recorded.
    Retries up to 3 times on failure.
    """
    try:
        from visits.models import Visit
        from notifications.services import create_notification

        visit = (
            Visit.objects.select_related("employee", "district")
            .filter(pk=visit_id)
            .first()
        )
        if not visit:
            logger.warning("notify_visit_created: visit_id=%s not found", visit_id)
            return

        # Notify the employee's admin (all staff users)
        from django.contrib.auth.models import User

        admins = User.objects.filter(is_staff=True, is_active=True)
        for admin in admins:
            create_notification(
                user=admin,
                notification_type="VISIT_CREATED",
                message=(
                    f"New visit by {visit.employee.username} "
                    f"for farmer {visit.farmer_name or visit.farmer_phone or 'Unknown'} "
                    f"on {visit.visit_date}."
                ),
            )

        logger.info("Notifications sent for visit_id=%s", visit_id)

    except Exception as exc:
        logger.exception("notify_visit_created failed for visit_id=%s", visit_id)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def generate_visit_report_pdf(self, visit_id: int, requested_by_user_id: int) -> None:
    """
    Generate a PDF summary for a single visit and store it in S3 / local media.
    """
    try:
        from visits.models import Visit
        from reports.tasks import build_and_store_pdf

        visit = Visit.objects.select_related(
            "employee", "village", "district", "crop"
        ).get(pk=visit_id)

        build_and_store_pdf(
            report_type="visit",
            object_id=visit.pk,
            requested_by_user_id=requested_by_user_id,
        )

    except Exception as exc:
        logger.exception("generate_visit_report_pdf failed for visit_id=%s", visit_id)
        raise self.retry(exc=exc)
