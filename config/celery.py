"""
Celery application configuration.

Usage (local / production):
    celery -A config worker -l info
    celery -A config beat -l info

Beat schedule (see settings.CELERY_BEAT_SCHEDULE):
    expire-overdue-duties-every-5-minutes → tracking.tasks.expire_overdue_duties_task

Fallback without beat:
    python manage.py expire_overdue_duties
"""

import logging
import os

from celery import Celery
from django.conf import settings

logger = logging.getLogger(__name__)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("agri_clinic")

# Pull config from Django settings, namespace="CELERY"
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    logger.debug("Request: %r", self.request)
