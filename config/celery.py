"""
Celery application configuration.

Usage:
    celery -A config worker -l info
    celery -A config beat -l info
"""

import os

from celery import Celery
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("agri_clinic")

# Pull config from Django settings, namespace="CELERY"
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    logger.debug("Request: %r", self.request)
