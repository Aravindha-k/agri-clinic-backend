"""Admin panel login lockout, session timeout, and IP restrictions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

logger = logging.getLogger(__name__)


def is_admin_user(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def get_client_ip(request) -> str | None:
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def admin_ip_allowed(request) -> bool:
    if not getattr(settings, "ADMIN_IP_WHITELIST_ENABLED", False):
        return True
    allowed = getattr(settings, "ADMIN_ALLOWED_IPS", []) or []
    if not allowed:
        return True
    ip = get_client_ip(request)
    return ip in allowed


@dataclass(frozen=True)
class AdminAccessCheck:
    ok: bool
    message: str = ""
    code: str = ""


def _timeout_delta() -> timedelta:
    minutes = int(getattr(settings, "ADMIN_SESSION_TIMEOUT_MINUTES", 30))
    return timedelta(minutes=minutes)


def _lockout_delta() -> timedelta:
    minutes = int(getattr(settings, "ADMIN_LOGIN_LOCKOUT_MINUTES", 15))
    return timedelta(minutes=minutes)


def _max_attempts() -> int:
    return int(getattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 5))


def get_or_create_security_state(user: User):
    from .models import AdminSecurityState

    state, _ = AdminSecurityState.objects.get_or_create(user=user)
    return state


def check_account_locked(user: User) -> AdminAccessCheck:
    state = get_or_create_security_state(user)
    if state.locked_until and state.locked_until > timezone.now():
        remaining = int((state.locked_until - timezone.now()).total_seconds() // 60) + 1
        return AdminAccessCheck(
            ok=False,
            message=f"Account locked due to failed login attempts. Try again in {remaining} minute(s).",
            code="ACCOUNT_LOCKED",
        )
    if state.locked_until and state.locked_until <= timezone.now():
        state.failed_login_attempts = 0
        state.locked_until = None
        state.save(update_fields=["failed_login_attempts", "locked_until"])
    return AdminAccessCheck(ok=True)


def record_failed_login(user: User | None, *, username: str = "") -> None:
    if user is None:
        user = User.objects.filter(username=username).first()
    if user is None or not is_admin_user(user):
        return
    state = get_or_create_security_state(user)
    state.failed_login_attempts = (state.failed_login_attempts or 0) + 1
    if state.failed_login_attempts >= _max_attempts():
        state.locked_until = timezone.now() + _lockout_delta()
        logger.warning(
            "Admin account locked user_id=%s attempts=%s until=%s",
            user.pk,
            state.failed_login_attempts,
            state.locked_until,
        )
    state.save(update_fields=["failed_login_attempts", "locked_until"])


def record_successful_admin_login(user: User, request) -> dict:
    from audit_logs.utils import create_audit_log

    now = timezone.now()
    ip = get_client_ip(request)
    state = get_or_create_security_state(user)
    state.failed_login_attempts = 0
    state.locked_until = None
    state.last_login_at = now
    state.last_activity_at = now
    state.last_login_ip = ip
    state.save(
        update_fields=[
            "failed_login_attempts",
            "locked_until",
            "last_login_at",
            "last_activity_at",
            "last_login_ip",
        ]
    )
    user.last_login = now
    user.save(update_fields=["last_login"])

    session = create_admin_session(user, request)
    create_audit_log(
        actor=user,
        module="AUTH",
        action="LOGIN",
        description=f"Admin login: {user.username}",
        request=request,
        metadata={"ip_address": ip},
    )
    logger.info("Admin login OK user_id=%s ip=%s", user.pk, ip)
    return {
        "admin_session_id": str(session.session_key),
        "session_timeout_minutes": int(
            getattr(settings, "ADMIN_SESSION_TIMEOUT_MINUTES", 30)
        ),
    }


def create_admin_session(user: User, request):
    from .models import AdminSession

    now = timezone.now()
    return AdminSession.objects.create(
        user=user,
        session_key=uuid.uuid4(),
        is_active=True,
        last_activity_at=now,
        ip_address=get_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
    )


def touch_admin_activity(user: User, request) -> AdminAccessCheck:
    if not is_admin_user(user):
        return AdminAccessCheck(ok=True)
    now = timezone.now()
    state = get_or_create_security_state(user)
    if state.last_activity_at and now - state.last_activity_at > _timeout_delta():
        deactivate_admin_sessions(user)
        return AdminAccessCheck(
            ok=False,
            message="Admin session expired due to inactivity. Please log in again.",
            code="ADMIN_SESSION_EXPIRED",
        )
    state.last_activity_at = now
    state.save(update_fields=["last_activity_at"])
    from .models import AdminSession

    AdminSession.objects.filter(user=user, is_active=True).update(last_activity_at=now)
    return AdminAccessCheck(ok=True)


def deactivate_admin_sessions(user: User) -> int:
    from .models import AdminSession

    return AdminSession.objects.filter(user=user, is_active=True).update(
        is_active=False
    )


def record_admin_logout(user: User, request) -> None:
    from audit_logs.utils import create_audit_log

    deactivate_admin_sessions(user)
    create_audit_log(
        actor=user,
        module="AUTH",
        action="LOGOUT",
        description=f"Admin logout: {user.username}",
        request=request,
    )
    logger.info("Admin logout user_id=%s", user.pk)


def issue_tokens_for_user(user: User):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    if is_admin_user(user):
        lifetime = _timeout_delta()
        refresh.set_exp(lifetime=lifetime)
        refresh.access_token.set_exp(lifetime=lifetime)
    return refresh


def build_admin_security_monitoring_payload() -> list[dict]:
    from .models import AdminSecurityState, AdminSession

    staff_users = User.objects.filter(is_staff=True).order_by("username")
    states = {
        s.user_id: s
        for s in AdminSecurityState.objects.filter(user__in=staff_users)
    }
    sessions = AdminSession.objects.filter(
        user__in=staff_users, is_active=True
    ).order_by("-last_activity_at")

    sessions_by_user: dict[int, list] = {}
    for session in sessions:
        sessions_by_user.setdefault(session.user_id, []).append(
            {
                "session_id": str(session.session_key),
                "created_at": session.created_at.isoformat(),
                "last_activity_at": session.last_activity_at.isoformat(),
                "ip_address": session.ip_address,
                "user_agent": session.user_agent,
            }
        )

    rows = []
    for user in staff_users:
        state = states.get(user.id)
        rows.append(
            {
                "user_id": user.id,
                "username": user.username,
                "is_active": user.is_active,
                "last_login": (
                    state.last_login_at.isoformat()
                    if state and state.last_login_at
                    else (user.last_login.isoformat() if user.last_login else None)
                ),
                "last_activity_at": (
                    state.last_activity_at.isoformat()
                    if state and state.last_activity_at
                    else None
                ),
                "last_login_ip": state.last_login_ip if state else None,
                "failed_login_attempts": state.failed_login_attempts if state else 0,
                "locked_until": (
                    state.locked_until.isoformat()
                    if state and state.locked_until
                    else None
                ),
                "active_sessions": sessions_by_user.get(user.id, []),
                "active_session_count": len(sessions_by_user.get(user.id, [])),
            }
        )
    return rows
