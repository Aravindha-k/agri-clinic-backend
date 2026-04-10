"""
notifications/services.py
──────────────────────────
Business logic for creating and managing in-app notifications.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from django.contrib.auth.models import User
from django.db import transaction

from .models import Notification

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Creation helpers
# ──────────────────────────────────────────────────────────────


def create_notification(
    *,
    user: Optional[User],
    notification_type: str,
    message: str,
) -> Notification:
    """
    Persist a single in-app notification for `user`.
    Passing user=None creates a broadcast notification (all staff will see it).
    """
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        message=message,
    )
    logger.debug(
        "Notification created: type=%s user_id=%s",
        notification_type,
        user.pk if user else "broadcast",
    )
    return notification


def broadcast_to_admins(*, notification_type: str, message: str) -> List[Notification]:
    """Send the same notification to all active staff users."""
    admins = User.objects.filter(is_staff=True, is_active=True)
    notifications = [
        create_notification(
            user=admin,
            notification_type=notification_type,
            message=message,
        )
        for admin in admins
    ]
    return notifications


# ──────────────────────────────────────────────────────────────
# Mark read / unread
# ──────────────────────────────────────────────────────────────


def mark_as_read(*, notification_id: int, user: User) -> bool:
    """Mark a single notification as read. Returns True if updated."""
    updated = Notification.objects.filter(pk=notification_id, user=user).update(
        is_read=True
    )
    return bool(updated)


def mark_all_as_read(*, user: User) -> int:
    """Mark all of a user's unread notifications as read. Returns count."""
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)


# ──────────────────────────────────────────────────────────────
# Queries (minimal – views should use these directly)
# ──────────────────────────────────────────────────────────────


def get_unread_count(user: User) -> int:
    return Notification.objects.filter(user=user, is_read=False).count()
