"""Canonical employee duty + GPS + heartbeat tracking status for admin APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from tracking.gps_state import is_mobile_gps_off
from tracking.live_tracking_service import (
    TRACKING_NO_LOCATION,
    TRACKING_OFFLINE,
    TRACKING_ONLINE,
    TRACKING_STALE,
    online_seconds,
    resolve_tracking_status,
    stale_seconds,
)
from utils.gps import validate_latitude, validate_longitude

# GPS fix freshness (location age) — separate from Online/Stale/Offline.
GPS_ACTIVE_MINUTES = 3
GPS_DELAYED_MINUTES = 10

DUTY_ON_DUTY = "ON_DUTY"
DUTY_OFF_DUTY = "OFF_DUTY"
DUTY_LOGGED_OUT = "LOGGED_OUT"

GPS_ACTIVE = "GPS_ACTIVE"
GPS_DELAYED = "GPS_DELAYED"
GPS_LOST = "GPS_LOST"
GPS_OFF = "GPS_OFF"


def coordinates_invalid(latitude, longitude) -> bool:
    if latitude is None or longitude is None:
        return False
    try:
        validate_latitude(latitude)
        validate_longitude(longitude)
        return False
    except Exception:
        return True


def resolve_duty_status(
    *,
    has_active_duty: bool,
    has_active_device_session: bool,
) -> str:
    if has_active_duty:
        return DUTY_ON_DUTY
    if has_active_device_session:
        return DUTY_OFF_DUTY
    return DUTY_LOGGED_OUT


def resolve_gps_status(
    *,
    last_gps_at: datetime | None,
    gps_enabled: bool | None = None,
    location_permission_status: str | None = None,
    gps_off: bool = False,
    latitude=None,
    longitude=None,
    now=None,
) -> str:
    if is_mobile_gps_off(
        gps_enabled=gps_enabled,
        location_permission_status=location_permission_status,
    ):
        return GPS_OFF
    if gps_off:
        return GPS_OFF
    if coordinates_invalid(latitude, longitude):
        return GPS_OFF
    if not last_gps_at:
        return GPS_OFF
    now = now or timezone.now()
    try:
        age_minutes = max(int((now - last_gps_at).total_seconds() // 60), 0)
    except (TypeError, ValueError):
        return GPS_OFF
    if age_minutes <= GPS_ACTIVE_MINUTES:
        return GPS_ACTIVE
    if age_minutes <= GPS_DELAYED_MINUTES:
        return GPS_DELAYED
    return GPS_LOST


def last_seen_minutes(last_at: datetime | None, *, now=None) -> int | None:
    if not last_at:
        return None
    now = now or timezone.now()
    try:
        return max(int((now - last_at).total_seconds() // 60), 0)
    except (TypeError, ValueError):
        return None


def _legacy_gps_signal(gps_status: str) -> str:
    return "GPS_ON" if gps_status in (GPS_ACTIVE, GPS_DELAYED) else "GPS_OFF"


def _legacy_tracking_health(
    *,
    duty_status: str,
    tracking_status: str,
) -> str:
    if duty_status != DUTY_ON_DUTY:
        return "STOPPED"
    if tracking_status == TRACKING_ONLINE:
        return "OK"
    if tracking_status == TRACKING_STALE:
        return "STALE"
    if tracking_status == TRACKING_NO_LOCATION:
        return "OK"
    return "STOPPED"


def build_employee_status_fields(
    *,
    has_active_duty: bool,
    has_active_device_session: bool,
    last_gps_at: datetime | None = None,
    latitude=None,
    longitude=None,
    gps_enabled: bool | None = None,
    location_permission_status: str | None = None,
    background_tracking_enabled: bool | None = None,
    gps_off: bool = False,
    last_heartbeat_at: datetime | None = None,
    now=None,
) -> dict[str, Any]:
    """Canonical status fields plus legacy aliases for admin clients."""
    now = now or timezone.now()
    duty_status = resolve_duty_status(
        has_active_duty=has_active_duty,
        has_active_device_session=has_active_device_session,
    )
    gps_status = resolve_gps_status(
        last_gps_at=last_gps_at,
        gps_enabled=gps_enabled,
        location_permission_status=location_permission_status,
        gps_off=gps_off,
        latitude=latitude,
        longitude=longitude,
        now=now,
    )
    # Presence: prefer heartbeat; fall back to last GPS for pre-migration rows.
    presence_at = last_heartbeat_at or last_gps_at
    tracking_status = resolve_tracking_status(
        has_active_duty=has_active_duty,
        last_heartbeat_at=presence_at,
        latitude=latitude,
        longitude=longitude,
        gps_enabled=False if gps_off else gps_enabled,
        location_permission_status=location_permission_status,
        background_tracking_enabled=background_tracking_enabled,
        now=now,
    )
    seen_minutes = last_seen_minutes(presence_at, now=now)
    last_gps_iso = (
        last_gps_at.isoformat()
        if last_gps_at and hasattr(last_gps_at, "isoformat")
        else None
    )
    last_hb_iso = (
        last_heartbeat_at.isoformat()
        if last_heartbeat_at and hasattr(last_heartbeat_at, "isoformat")
        else None
    )
    permission_granted = None
    if location_permission_status == "granted":
        permission_granted = True
    elif location_permission_status in {"denied", "services_disabled"}:
        permission_granted = False

    return {
        "duty_status": duty_status,
        "gps_status": gps_status,
        "tracking_status": tracking_status,
        "gps_enabled": gps_enabled,
        "permission_granted": permission_granted,
        "tracking_service_active": background_tracking_enabled,
        "location_permission_status": location_permission_status,
        "background_tracking_enabled": background_tracking_enabled,
        "last_gps_update": last_gps_iso,
        "last_heartbeat_at": last_hb_iso,
        "location_recorded_at": last_gps_iso,
        "last_seen_minutes": seen_minutes,
        "online_threshold_seconds": online_seconds(),
        "stale_threshold_seconds": stale_seconds(),
        # Legacy aliases — connection now mirrors heartbeat-based tracking_status
        "is_on_duty": duty_status == DUTY_ON_DUTY,
        "last_update": last_hb_iso or last_gps_iso,
        "last_update_age_minutes": seen_minutes,
        "connection": tracking_status,
        "gps_signal": _legacy_gps_signal(gps_status),
        "legacy_gps_status": _legacy_gps_signal(gps_status),
        "tracking_health": _legacy_tracking_health(
            duty_status=duty_status,
            tracking_status=tracking_status,
        ),
    }


def build_status_for_live_employee(
    *,
    user_id: int,
    live_row,
    gps_state_row=None,
    has_active_duty: bool,
    device_status: dict | None,
    gps_off: bool = False,
    last_heartbeat_at=None,
    now=None,
) -> dict[str, Any]:
    """Status block for admin live map / day report rows."""
    from tracking.gps_state import resolve_stored_gps_state

    stored = resolve_stored_gps_state(gps_state_row=gps_state_row, live_row=live_row)
    last_gps_at = live_row.recorded_at if live_row else None
    latitude = float(live_row.latitude) if live_row and live_row.latitude is not None else None
    longitude = (
        float(live_row.longitude) if live_row and live_row.longitude is not None else None
    )
    hb = last_heartbeat_at
    if hb is None and live_row is not None:
        hb = getattr(live_row, "last_heartbeat_at", None)
    return build_employee_status_fields(
        has_active_duty=has_active_duty,
        has_active_device_session=bool(device_status and device_status.get("is_active")),
        last_gps_at=last_gps_at,
        latitude=latitude,
        longitude=longitude,
        gps_enabled=stored.get("gps_enabled"),
        location_permission_status=stored.get("location_permission_status"),
        background_tracking_enabled=stored.get("background_tracking_enabled"),
        gps_off=gps_off,
        last_heartbeat_at=hb,
        now=now,
    )


def batch_gps_off_user_ids(user_ids: list[int]) -> set[int]:
    """Legacy AvailabilityEvent GPS_OFF rows (fallback when mobile state missing)."""
    if not user_ids:
        return set()
    from tracking.models import AvailabilityEvent

    return set(
        AvailabilityEvent.objects.filter(
            user_id__in=user_ids,
            event_type="GPS_OFF",
            end_time__isnull=True,
        ).values_list("user_id", flat=True)
    )
