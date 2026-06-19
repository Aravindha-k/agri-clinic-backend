"""Parse and persist mobile-reported GPS device state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.contrib.auth.models import User
from django.utils import timezone

from tracking.models import EmployeeGpsState, EmployeeLiveLocation

PERMISSION_GRANTED = "granted"
PERMISSION_DENIED = "denied"
PERMISSION_SERVICES_DISABLED = "services_disabled"

GPS_OFF_PERMISSION_STATUSES = frozenset({PERMISSION_DENIED, PERMISSION_SERVICES_DISABLED})


def _parse_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    return bool(value)


def parse_mobile_gps_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Extract gps_enabled, location_permission_status, background_tracking_enabled."""
    payload = payload or {}
    permission = payload.get("location_permission_status")
    if permission is not None:
        permission = str(permission).strip().lower() or None
    return {
        "gps_enabled": _parse_bool(payload.get("gps_enabled")),
        "location_permission_status": permission,
        "background_tracking_enabled": _parse_bool(
            payload.get("background_tracking_enabled")
        ),
    }


def is_mobile_gps_off(
    *,
    gps_enabled: bool | None = None,
    location_permission_status: str | None = None,
) -> bool:
    if gps_enabled is False:
        return True
    if location_permission_status in GPS_OFF_PERMISSION_STATUSES:
        return True
    return False


def gps_state_response_fields(state: dict[str, Any] | None) -> dict[str, Any]:
    state = state or {}
    return {
        "gps_enabled": state.get("gps_enabled"),
        "location_permission_status": state.get("location_permission_status"),
        "background_tracking_enabled": state.get("background_tracking_enabled"),
    }


def _model_to_dict(row: EmployeeGpsState | EmployeeLiveLocation | None) -> dict[str, Any]:
    if not row:
        return {
            "gps_enabled": None,
            "location_permission_status": None,
            "background_tracking_enabled": None,
            "reported_at": None,
        }
    return {
        "gps_enabled": row.gps_enabled,
        "location_permission_status": row.location_permission_status,
        "background_tracking_enabled": row.background_tracking_enabled,
        "reported_at": row.reported_at if hasattr(row, "reported_at") else None,
    }


def resolve_stored_gps_state(
    *,
    gps_state_row: EmployeeGpsState | None = None,
    live_row: EmployeeLiveLocation | None = None,
) -> dict[str, Any]:
    """Prefer dedicated gps_state row; fall back to denormalized live location copy."""
    if gps_state_row and gps_state_row.reported_at:
        return _model_to_dict(gps_state_row)
    if live_row and live_row.gps_reported_at:
        return _model_to_dict(live_row)
    if gps_state_row:
        return _model_to_dict(gps_state_row)
    return _model_to_dict(live_row)


def upsert_employee_gps_state(
    user: User,
    payload: dict[str, Any] | None,
    *,
    reported_at: datetime | None = None,
    sync_live_location: bool = True,
) -> EmployeeGpsState | None:
    """Persist mobile GPS device state from location update, bulk, or heartbeat."""
    fields = parse_mobile_gps_state(payload)
    if all(v is None for v in fields.values()):
        return EmployeeGpsState.objects.filter(user=user).first()

    now = reported_at or timezone.now()
    state, _created = EmployeeGpsState.objects.update_or_create(
        user=user,
        defaults={**fields, "reported_at": now},
    )

    if sync_live_location:
        live = EmployeeLiveLocation.objects.filter(user=user).first()
        if live:
            EmployeeLiveLocation.objects.filter(pk=live.pk).update(
                gps_enabled=fields["gps_enabled"],
                location_permission_status=fields["location_permission_status"],
                background_tracking_enabled=fields["background_tracking_enabled"],
                gps_reported_at=now,
            )

    return state


def gps_state_defaults_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Defaults dict for EmployeeLiveLocation update_or_create."""
    fields = parse_mobile_gps_state(payload)
    if all(v is None for v in fields.values()):
        return {}
    return {
        **fields,
        "gps_reported_at": timezone.now(),
    }
