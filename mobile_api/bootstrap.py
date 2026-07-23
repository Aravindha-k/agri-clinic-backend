"""Canonical mobile bootstrap payload for app startup / restore."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from tracking.day_map_service import build_duty_day_map
from tracking.duty_service import serialize_duty_status
from tracking.models import DutySession

logger = logging.getLogger(__name__)


def build_day_map_summary(day_map: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact map summary for bootstrap (full map via /duty/.../map/)."""
    if not day_map:
        return None
    duty = day_map.get("duty") or {}
    summary = day_map.get("summary") or {}
    meta = day_map.get("metadata") or {}
    return {
        "duty_session_id": duty.get("id") or duty.get("duty_session_id"),
        "visit_count": summary.get("visit_count"),
        "route_point_count": summary.get("route_point_count"),
        "distance_meters": summary.get("distance_meters"),
        "route_source": meta.get("route_source"),
        "has_start_marker": day_map.get("start_marker") is not None,
        "has_end_marker": day_map.get("end_marker") is not None,
        "map_bounds": day_map.get("map_bounds"),
        "full_map_path": (
            f"/api/v1/tracking/duty/{duty.get('id')}/map/"
            if duty.get("id")
            else "/api/v1/tracking/duty/current/map/"
        ),
    }


def build_mobile_bootstrap(*, request) -> dict[str, Any]:
    """
    Canonical authenticated bootstrap for mobile restore.

    Uses serialize_duty_status + day_map_service. Does not embed full routes.
    """
    user = request.user
    profile = getattr(user, "employee_profile", None)
    from accounts.employee_photo import employee_me_payload

    user_block = employee_me_payload(request, profile) if profile else {
        "id": user.pk,
        "username": user.username,
    }

    session_id = request.headers.get("X-Device-Session") or request.META.get(
        "HTTP_X_DEVICE_SESSION"
    )
    device_session = {
        "id": session_id,
        "status": "ACTIVE" if session_id else "UNKNOWN",
    }

    current_duty = serialize_duty_status(user)
    day_map_summary = None
    duty_id = current_duty.get("duty_session_id")
    if duty_id:
        duty = (
            DutySession.objects.select_related("user", "workday")
            .filter(pk=duty_id)
            .first()
        )
        if duty:
            try:
                full_map = build_duty_day_map(
                    duty,
                    viewer=user,
                    include_live_location=bool(duty.is_active),
                )
                day_map_summary = build_day_map_summary(full_map)
            except Exception:
                logger.exception(
                    "event=bootstrap_day_map_failed user_id=%s duty_id=%s",
                    user.pk,
                    duty_id,
                )

    min_version = getattr(settings, "MINIMUM_SUPPORTED_APP_VERSION", None)
    force_update = bool(getattr(settings, "FORCE_APP_UPDATE", False))

    live_tracking = None
    if current_duty.get("duty_session_id") and current_duty.get("is_active"):
        from tracking.live_tracking_service import resolve_tracking_status
        from tracking.models import EmployeeLiveLocation

        live = EmployeeLiveLocation.objects.filter(user=user).first()
        hb = None
        if live and live.last_heartbeat_at:
            hb = live.last_heartbeat_at
        elif current_duty.get("last_heartbeat"):
            from django.utils.dateparse import parse_datetime

            hb = parse_datetime(current_duty["last_heartbeat"]) or None
        live_tracking = {
            "duty_session_id": current_duty.get("duty_session_id"),
            "last_heartbeat_at": hb.isoformat() if hb else None,
            "location_recorded_at": (
                live.recorded_at.isoformat()
                if live and live.recorded_at
                else None
            ),
            "latitude": float(live.latitude) if live and live.latitude is not None else None,
            "longitude": (
                float(live.longitude) if live and live.longitude is not None else None
            ),
            "gps_enabled": live.gps_enabled if live else None,
            "permission_granted": (
                True
                if live and live.location_permission_status == "granted"
                else False
                if live and live.location_permission_status in {"denied", "services_disabled"}
                else None
            ),
            "tracking_service_active": (
                live.background_tracking_enabled if live else None
            ),
            "tracking_status": resolve_tracking_status(
                has_active_duty=True,
                last_heartbeat_at=hb,
                latitude=live.latitude if live else None,
                longitude=live.longitude if live else None,
                gps_enabled=live.gps_enabled if live else None,
                location_permission_status=(
                    live.location_permission_status if live else None
                ),
                background_tracking_enabled=(
                    live.background_tracking_enabled if live else None
                ),
            ),
            "expected_end_at": current_duty.get("expected_end_at"),
        }

    return {
        "user": user_block,
        "device_session": device_session,
        "current_duty": current_duty if current_duty.get("duty_session_id") else None,
        "live_tracking": live_tracking,
        "day_map": day_map_summary,
        "server_now": timezone.now().isoformat(),
        "feature_flags": {
            "canonical_duty": True,
            "canonical_gps": True,
            "canonical_visits": True,
            "canonical_day_map": True,
            "duty_start_end_route_points": True,
            "heartbeat_live_tracking": True,
        },
        "minimum_supported_app_version": min_version,
        "force_update": force_update,
    }
