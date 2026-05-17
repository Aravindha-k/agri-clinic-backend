"""Workday duration limits and auto-end helpers."""

from datetime import timedelta

from django.utils import timezone

from .models import WorkDay

MAX_WORKDAY_DURATION = timedelta(hours=9)


def expire_overlong_workdays_for_user(user, *, now=None):
    """
    End active workdays whose elapsed time exceeds MAX_WORKDAY_DURATION.
    Location history is preserved; only WorkDay flags are updated.
    Returns the number of workdays closed.
    """
    if not user or not user.is_authenticated:
        return 0
    now = now or timezone.now()
    cutoff = now - MAX_WORKDAY_DURATION
    return WorkDay.objects.filter(
        user=user, is_active=True, start_time__lte=cutoff
    ).update(end_time=now, is_active=False, auto_ended=True)
