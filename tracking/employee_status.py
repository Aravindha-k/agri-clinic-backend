"""Canonical employee duty + GPS status for admin APIs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from tracking.gps_state import is_mobile_gps_off
from utils.gps import validate_latitude, validate_longitude

# GPS freshness thresholds (minutes)
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


def last_seen_minutes(last_gps_at: datetime | None, *, now=None) -> int | None:
    if not last_gps_at:
        return None
    now = now or timezone.now()
    try:
        return max(int((now - last_gps_at).total_seconds() // 60), 0)
    except (TypeError, ValueError):
        return None


def _legacy_connection(gps_status: str) -> str:
    return "ONLINE" if gps_status in (GPS_ACTIVE, GPS_DELAYED) else "OFFLINE"


def _legacy_gps_signal(gps_status: str) -> str:
    return "GPS_ON" if gps_status in (GPS_ACTIVE, GPS_DELAYED) else "GPS_OFF"


def _legacy_tracking_health(
    *,
    duty_status: str,
    gps_status: str,
    last_heartbeat_at: datetime | None,
    now=None,
) -> str:
    if duty_status != DUTY_ON_DUTY:
        return "STOPPED"
    if gps_status == GPS_ACTIVE:
        return "OK"
    if gps_status == GPS_DELAYED:
        return "STALE"
    if last_heartbeat_at:
        now = now or timezone.now()
        diff = (now - last_heartbeat_at).total_seconds() / 60
        if diff <= GPS_ACTIVE_MINUTES:
            return "OK"
        if diff <= GPS_DELAYED_MINUTES:
            return "STALE"
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
    """New canonical status fields plus legacy aliases for admin clients."""
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
    seen_minutes = last_seen_minutes(last_gps_at, now=now)
    last_gps_iso = (
        last_gps_at.isoformat()
        if last_gps_at and hasattr(last_gps_at, "isoformat")
        else None
    )

    return {
        "duty_status": duty_status,
        "gps_status": gps_status,
        "gps_enabled": gps_enabled,
        "location_permission_status": location_permission_status,
        "background_tracking_enabled": background_tracking_enabled,
        "last_gps_update": last_gps_iso,
        "last_seen_minutes": seen_minutes,
        # Legacy aliases
        "is_on_duty": duty_status == DUTY_ON_DUTY,
        "last_update": last_gps_iso,
        "last_update_age_minutes": seen_minutes,
        "connection": _legacy_connection(gps_status),
        "gps_signal": _legacy_gps_signal(gps_status),
        "legacy_gps_status": _legacy_gps_signal(gps_status),
        "tracking_health": _legacy_tracking_health(
            duty_status=duty_status,
            gps_status=gps_status,
            last_heartbeat_at=last_heartbeat_at,
            now=now,
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
    latitude = float(live_row.latitude) if live_row else None
    longitude = float(live_row.longitude) if live_row else None
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
        last_heartbeat_at=last_heartbeat_at,
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
