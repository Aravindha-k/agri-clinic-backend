"""Heartbeat-backed live tracking state (separate from Route History)."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tracking.gps_state import (
    is_mobile_gps_off,
    parse_mobile_gps_state,
    upsert_employee_gps_state,
)
from tracking.models import DutySession, EmployeeLiveLocation, WorkDay
from utils.gps import validate_latitude_longitude

logger = logging.getLogger(__name__)

TRACKING_ONLINE = "ONLINE"
TRACKING_STALE = "STALE"
TRACKING_OFFLINE = "OFFLINE"
TRACKING_NO_LOCATION = "NO_LOCATION_YET"

DUTY_WORKING = "WORKING"
DUTY_STOPPED = "STOPPED"
DUTY_AUTO_ENDED = "AUTO_ENDED"
DUTY_ADMIN_ENDED = "ADMIN_ENDED"
DUTY_NO_WORKDAY = "NO_WORKDAY"


class LiveTrackingError(Exception):
    def __init__(self, message: str, code: str = "LIVE_TRACKING_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


def online_seconds() -> int:
    return int(getattr(settings, "LIVE_TRACKING_ONLINE_SECONDS", 7 * 60))


def stale_seconds() -> int:
    return int(getattr(settings, "LIVE_TRACKING_STALE_SECONDS", 15 * 60))


def _parse_client_dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime(str(value))
        if dt is None:
            raise LiveTrackingError("Invalid recorded_at timestamp", "INVALID_TIMESTAMP")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def resolve_duty_display_status(duty: DutySession | None) -> str:
    if duty is None:
        return DUTY_NO_WORKDAY
    if duty.is_active:
        return DUTY_WORKING
    if duty.auto_ended or (duty.completion_reason or "").upper() == "AUTO_EXPIRED":
        return DUTY_AUTO_ENDED
    if (duty.completion_reason or "").upper() in {"ADMIN", "ADMIN_ENDED", "FORCE_END"}:
        return DUTY_ADMIN_ENDED
    return DUTY_STOPPED


def resolve_tracking_status(
    *,
    has_active_duty: bool,
    last_heartbeat_at: datetime | None,
    latitude=None,
    longitude=None,
    gps_enabled: bool | None = None,
    location_permission_status: str | None = None,
    background_tracking_enabled: bool | None = None,
    tracking_service_active: bool | None = None,
    permission_granted: bool | None = None,
    now: datetime | None = None,
) -> str:
    """
    Heartbeat-primary Online / Stale / Offline.

    Duty Working is independent — Offline GPS does not end the workday.
    """
    now = now or timezone.now()

    service_active = tracking_service_active
    if service_active is None:
        service_active = background_tracking_enabled

    if permission_granted is False:
        return TRACKING_OFFLINE
    if permission_granted is None and location_permission_status in {
        "denied",
        "services_disabled",
    }:
        return TRACKING_OFFLINE
    if gps_enabled is False or service_active is False:
        return TRACKING_OFFLINE
    if is_mobile_gps_off(
        gps_enabled=gps_enabled,
        location_permission_status=location_permission_status,
    ):
        return TRACKING_OFFLINE

    has_coords = latitude is not None and longitude is not None
    if has_active_duty and not has_coords:
        # Still report heartbeat freshness when known; otherwise No Location Yet.
        if last_heartbeat_at is None:
            return TRACKING_NO_LOCATION

    if last_heartbeat_at is None:
        if has_active_duty and not has_coords:
            return TRACKING_NO_LOCATION
        return TRACKING_OFFLINE

    age = (now - last_heartbeat_at).total_seconds()
    if age < 0:
        age = 0
    if age <= online_seconds():
        if has_active_duty and not has_coords:
            return TRACKING_NO_LOCATION
        return TRACKING_ONLINE
    if age <= stale_seconds():
        if has_active_duty and not has_coords:
            return TRACKING_NO_LOCATION
        return TRACKING_STALE
    return TRACKING_OFFLINE


def _quantize(lat, lng) -> tuple[Decimal, Decimal]:
    return (
        Decimal(str(lat)).quantize(Decimal("0.000001")),
        Decimal(str(lng)).quantize(Decimal("0.000001")),
    )


@transaction.atomic
def ensure_live_row_for_duty(user: User, duty: DutySession) -> EmployeeLiveLocation:
    """Create or attach live-state row for an active duty (coords optional)."""
    now = timezone.now()
    live, created = EmployeeLiveLocation.objects.select_for_update().get_or_create(
        user=user,
        defaults={
            "duty_session": duty,
            "last_heartbeat_at": now,
            "recorded_at": None,
            "latitude": None,
            "longitude": None,
        },
    )
    updates = []
    if live.duty_session_id != duty.pk:
        live.duty_session = duty
        updates.append("duty_session")
    if live.last_heartbeat_at is None:
        live.last_heartbeat_at = now
        updates.append("last_heartbeat_at")
    if updates:
        live.save(update_fields=updates)
    if created:
        logger.info(
            "event=live_state_created user_id=%s duty_id=%s",
            user.pk,
            duty.pk,
        )
    return live


def apply_heartbeat(
    user: User,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Accept a mobile heartbeat during active duty.

    Coordinates are optional. Never creates Route History points.
    """
    from tracking.duty_service import get_active_duty

    payload = dict(payload or {})
    if user.is_staff:
        raise LiveTrackingError("Admins cannot send heartbeat", "FORBIDDEN")

    duty = get_active_duty(user)
    if duty is None:
        raise LiveTrackingError("No active duty session", "NO_ACTIVE_DUTY")

    expected_duty = payload.get("duty_session_id")
    if expected_duty not in (None, ""):
        try:
            expected_id = int(expected_duty)
        except (TypeError, ValueError) as exc:
            raise LiveTrackingError("Invalid duty_session_id", "VALIDATION_ERROR") from exc
        if expected_id != duty.pk:
            raise LiveTrackingError(
                "duty_session_id does not match the active duty",
                "DUTY_MISMATCH",
            )

    client_hb_id = payload.get("client_heartbeat_id") or payload.get("client_point_id")
    if isinstance(client_hb_id, str):
        client_hb_id = client_hb_id.strip() or None

    recorded_at = _parse_client_dt(payload.get("recorded_at")) or timezone.now()
    # Reject far-future clocks (>5 min) to avoid permanent Online.
    skew = (recorded_at - timezone.now()).total_seconds()
    if skew > 300:
        raise LiveTrackingError(
            "recorded_at is too far in the future",
            "INVALID_TIMESTAMP",
        )

    with transaction.atomic():
        live = (
            EmployeeLiveLocation.objects.select_for_update()
            .filter(user=user)
            .first()
        )
        if live is None:
            live = ensure_live_row_for_duty(user, duty)
            live = (
                EmployeeLiveLocation.objects.select_for_update()
                .filter(pk=live.pk)
                .first()
            )

        # Idempotent replay of the same client heartbeat id.
        if (
            client_hb_id
            and live.last_client_heartbeat_id == client_hb_id
            and live.last_heartbeat_at is not None
        ):
            logger.info(
                "event=heartbeat_duplicate user_id=%s duty_id=%s client_id=%s",
                user.pk,
                duty.pk,
                client_hb_id,
            )
            return _heartbeat_response(duty, live, accepted=recorded_at, duplicate=True)

        # Stale heartbeat must not move last_heartbeat_at backwards.
        if live.last_heartbeat_at and recorded_at < live.last_heartbeat_at:
            logger.info(
                "event=heartbeat_stale_ignored user_id=%s duty_id=%s "
                "incoming=%s current=%s",
                user.pk,
                duty.pk,
                recorded_at.isoformat(),
                live.last_heartbeat_at.isoformat(),
            )
            return _heartbeat_response(
                duty, live, accepted=live.last_heartbeat_at, duplicate=False, stale=True
            )

        gps_fields = parse_mobile_gps_state(payload)
        if "tracking_service_active" in payload and payload.get(
            "background_tracking_enabled"
        ) is None:
            gps_fields["background_tracking_enabled"] = (
                True
                if payload.get("tracking_service_active") in (True, "true", "1", 1)
                else False
                if payload.get("tracking_service_active") in (False, "false", "0", 0)
                else None
            )
        if payload.get("permission_granted") is True and not gps_fields.get(
            "location_permission_status"
        ):
            gps_fields["location_permission_status"] = "granted"
        if payload.get("permission_granted") is False and not gps_fields.get(
            "location_permission_status"
        ):
            gps_fields["location_permission_status"] = "denied"

        live.duty_session = duty
        live.last_heartbeat_at = recorded_at
        if client_hb_id:
            live.last_client_heartbeat_id = client_hb_id
        if payload.get("app_state") not in (None, ""):
            live.app_state = str(payload.get("app_state"))[:32]
        if "network_available" in payload:
            live.network_available = bool(payload.get("network_available"))

        update_fields = [
            "duty_session",
            "last_heartbeat_at",
            "last_client_heartbeat_id",
            "app_state",
            "network_available",
            "updated_at",
        ]
        for key, value in gps_fields.items():
            if value is not None or key in payload:
                setattr(live, key, value)
                update_fields.append(key)
        if any(v is not None for v in gps_fields.values()):
            live.gps_reported_at = recorded_at
            update_fields.append("gps_reported_at")

        # Optional coordinate on heartbeat — update only if newer than live fix.
        lat = payload.get("latitude")
        lng = payload.get("longitude")
        if lat not in (None, "") and lng not in (None, ""):
            try:
                lat_f, lng_f = validate_latitude_longitude(lat, lng)
            except Exception as exc:
                raise LiveTrackingError(str(exc), "INVALID_COORDS") from exc
            loc_ts = recorded_at
            if live.recorded_at is None or loc_ts >= live.recorded_at:
                lat_dec, lng_dec = _quantize(lat_f, lng_f)
                live.latitude = lat_dec
                live.longitude = lng_dec
                live.recorded_at = loc_ts
                if payload.get("latest_accuracy") is not None:
                    live.accuracy = float(payload.get("latest_accuracy"))
                elif payload.get("accuracy") is not None:
                    live.accuracy = float(payload.get("accuracy"))
                update_fields.extend(
                    ["latitude", "longitude", "recorded_at", "accuracy"]
                )

        live.save(update_fields=list(dict.fromkeys(update_fields)))

        DutySession.objects.filter(pk=duty.pk).update(last_heartbeat=recorded_at)
        if duty.workday_id:
            WorkDay.objects.filter(pk=duty.workday_id).update(last_heartbeat=recorded_at)

        upsert_employee_gps_state(
            user, {**payload, **gps_fields}, reported_at=recorded_at, sync_live_location=False
        )

        # AvailabilityEvent GPS_OFF open/close (legacy)
        from tracking.models import AvailabilityEvent

        if gps_fields.get("gps_enabled") is False and duty.workday_id:
            AvailabilityEvent.objects.get_or_create(
                user=user,
                workday_id=duty.workday_id,
                event_type="GPS_OFF",
                end_time__isnull=True,
                defaults={"start_time": recorded_at},
            )
        elif gps_fields.get("gps_enabled") is True and duty.workday_id:
            AvailabilityEvent.objects.filter(
                user=user,
                workday_id=duty.workday_id,
                event_type="GPS_OFF",
                end_time__isnull=True,
            ).update(end_time=recorded_at)

    live.refresh_from_db()
    logger.info(
        "event=heartbeat_accepted user_id=%s duty_id=%s recorded_at=%s",
        user.pk,
        duty.pk,
        recorded_at.isoformat(),
    )
    return _heartbeat_response(duty, live, accepted=recorded_at, duplicate=False)


def _heartbeat_response(
    duty: DutySession,
    live: EmployeeLiveLocation,
    *,
    accepted: datetime,
    duplicate: bool = False,
    stale: bool = False,
) -> dict[str, Any]:
    now = timezone.now()
    tracking_status = resolve_tracking_status(
        has_active_duty=duty.is_active,
        last_heartbeat_at=live.last_heartbeat_at,
        latitude=live.latitude,
        longitude=live.longitude,
        gps_enabled=live.gps_enabled,
        location_permission_status=live.location_permission_status,
        background_tracking_enabled=live.background_tracking_enabled,
        now=now,
    )
    return {
        "success": True,
        "server_now": now.isoformat(),
        "duty_session_id": duty.pk,
        "accepted_recorded_at": accepted.isoformat() if accepted else None,
        "tracking_status": tracking_status,
        "duty_status": resolve_duty_display_status(duty),
        "duplicate": duplicate,
        "stale_ignored": stale,
        "last_heartbeat_at": (
            live.last_heartbeat_at.isoformat() if live.last_heartbeat_at else None
        ),
        "location_recorded_at": (
            live.recorded_at.isoformat() if live.recorded_at else None
        ),
        "latitude": float(live.latitude) if live.latitude is not None else None,
        "longitude": float(live.longitude) if live.longitude is not None else None,
    }


def update_live_state_from_gps(
    *,
    user: User,
    duty: DutySession,
    latitude: float,
    longitude: float,
    recorded_at: datetime,
    accuracy=None,
    speed=None,
    heading=None,
    battery_level=None,
    client_point_id: str | None = None,
    gps_defaults: dict[str, Any] | None = None,
) -> tuple[EmployeeLiveLocation, bool]:
    """
    Upsert live state from an accepted GPS point.

    Returns (live_row, location_updated). Older recorded_at never overwrites
    a newer coordinate, but heartbeat still advances to server-now.
    """
    now = timezone.now()
    lat_dec, lng_dec = _quantize(latitude, longitude)
    gps_defaults = dict(gps_defaults or {})

    with transaction.atomic():
        live = (
            EmployeeLiveLocation.objects.select_for_update()
            .filter(user=user)
            .first()
        )
        if live is None:
            live = EmployeeLiveLocation(
                user=user,
                duty_session=duty,
                latitude=lat_dec,
                longitude=lng_dec,
                accuracy=accuracy,
                speed=speed,
                heading=heading,
                battery_level=battery_level,
                recorded_at=recorded_at,
                last_heartbeat_at=now,
                last_client_point_id=client_point_id,
                **gps_defaults,
            )
            live.save()
            logger.info(
                "event=live_state_updated user_id=%s duty_id=%s reason=gps_create",
                user.pk,
                duty.pk,
            )
            return live, True

        location_updated = False
        if live.recorded_at is None or recorded_at >= live.recorded_at:
            live.latitude = lat_dec
            live.longitude = lng_dec
            live.accuracy = accuracy
            live.speed = speed
            live.heading = heading
            live.battery_level = battery_level
            live.recorded_at = recorded_at
            if client_point_id:
                live.last_client_point_id = client_point_id
            location_updated = True
        else:
            logger.info(
                "event=live_state_stale_gps_ignored user_id=%s duty_id=%s "
                "incoming=%s current=%s",
                user.pk,
                duty.pk,
                recorded_at.isoformat(),
                live.recorded_at.isoformat() if live.recorded_at else None,
            )

        live.duty_session = duty
        # Receiving GPS is presence — advance heartbeat to server now unless
        # already newer (should not happen).
        if live.last_heartbeat_at is None or now >= live.last_heartbeat_at:
            live.last_heartbeat_at = now
        for key, value in gps_defaults.items():
            setattr(live, key, value)
        live.save()
        return live, location_updated


def finalize_live_state_on_duty_end(user: User, duty: DutySession) -> None:
    """Detach active duty from live row without inventing coordinates."""
    EmployeeLiveLocation.objects.filter(user=user, duty_session=duty).update(
        duty_session=None
    )
    logger.info(
        "event=live_state_finalized user_id=%s duty_id=%s",
        user.pk,
        duty.pk,
    )


def tracking_status_sort_key(status: str) -> int:
    order = {
        TRACKING_ONLINE: 0,
        TRACKING_STALE: 1,
        TRACKING_OFFLINE: 2,
        TRACKING_NO_LOCATION: 3,
    }
    return order.get(status, 9)
