"""Canonical GPS / route-point write path (Phase 4).

Authoritative storage: EmployeeRoutePoint (owned by DutySession).
Legacy LocationLog is written as a compatibility mirror when a WorkDay exists.

Idempotency: (duty_session_id, client_point_id) when client_point_id is provided.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import EmployeeProfile
from tracking.gps_state import gps_state_defaults_from_payload, upsert_employee_gps_state
from tracking.models import (
    DutySession,
    EmployeeLiveLocation,
    EmployeeRoutePoint,
    LocationLog,
    WorkDay,
)
from tracking.route_point_filter import should_save_route_point
from tracking.services import refresh_workday_live_state
from tracking.workday_utils import WORKDAY_EXPIRED_MESSAGE, expire_overlong_workdays_for_user
from utils.gps import validate_latitude_longitude

logger = logging.getLogger(__name__)

MAX_BULK_LOCATION_POINTS = 500
# Allow minor device/server clock skew; still blocks yesterday's points on today's duty.
DUTY_POINT_CLOCK_SKEW = timedelta(minutes=15)


class GpsTrackingError(Exception):
    def __init__(self, message: str, code: str = "GPS_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


def _ensure_field_employee(user: User) -> None:
    if user.is_staff:
        raise GpsTrackingError("Admins cannot push GPS", "FORBIDDEN")
    if not user.is_active:
        raise GpsTrackingError("Account disabled", "ACCOUNT_DISABLED")
    profile = EmployeeProfile.objects.filter(user=user).first()
    if profile and not profile.is_active_employee:
        raise GpsTrackingError("Inactive employee", "FORBIDDEN")


def parse_recorded_at(raw) -> datetime:
    if raw is None:
        return timezone.now()
    if isinstance(raw, datetime):
        return raw if timezone.is_aware(raw) else timezone.make_aware(raw)
    if isinstance(raw, str):
        parsed = parse_datetime(raw.strip())
        if parsed is not None:
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    raise GpsTrackingError("Invalid recorded_at timestamp", "INVALID_TIMESTAMP")


def extract_client_point_id(payload: dict[str, Any]) -> str | None:
    raw = payload.get("client_point_id") or payload.get("local_point_id")
    if raw in (None, ""):
        return None
    value = str(raw).strip()
    return value or None


def _validate_duty_ownership(user: User, duty: DutySession, payload: dict[str, Any]) -> None:
    if duty.user_id != user.pk:
        raise GpsTrackingError(
            "DutySession belongs to another employee",
            "WRONG_DUTY_OWNER",
        )
    if not duty.is_active:
        raise GpsTrackingError(WORKDAY_EXPIRED_MESSAGE, "NO_ACTIVE_DUTY")

    duty_session_id = payload.get("duty_session_id")
    if duty_session_id not in (None, ""):
        try:
            if int(duty_session_id) != duty.pk:
                raise GpsTrackingError(
                    "duty_session_id does not match active duty session",
                    "WRONG_DUTY",
                )
        except (TypeError, ValueError) as exc:
            raise GpsTrackingError("Invalid duty_session_id", "WRONG_DUTY") from exc

    workday_id = payload.get("workday_id")
    if workday_id not in (None, "") and duty.workday_id:
        try:
            if int(workday_id) != duty.workday_id:
                raise GpsTrackingError(
                    "workday_id does not match active duty workday",
                    "WRONG_WORKDAY",
                )
        except (TypeError, ValueError) as exc:
            raise GpsTrackingError("Invalid workday_id", "WRONG_WORKDAY") from exc


def _validate_recorded_at_within_duty(
    duty: DutySession, recorded_at: datetime
) -> None:
    """
    Prevent offline/bulk GPS from attaching a prior workday's points to the
    currently active DutySession when the client omits duty_session_id.
    """
    if not duty.start_time:
        return
    window_start = duty.start_time - DUTY_POINT_CLOCK_SKEW
    window_end = (duty.end_time or timezone.now()) + DUTY_POINT_CLOCK_SKEW
    if recorded_at < window_start or recorded_at > window_end:
        raise GpsTrackingError(
            "GPS point timestamp is outside the active duty session window",
            "OUTSIDE_DUTY_WINDOW",
        )


def _quantize(lat: float, lng: float) -> tuple[Decimal, Decimal]:
    return (
        Decimal(str(lat)).quantize(Decimal("0.000001")),
        Decimal(str(lng)).quantize(Decimal("0.000001")),
    )


def _serialize_point_result(
    *,
    live: EmployeeLiveLocation,
    route_point: EmployeeRoutePoint | None,
    location_log: LocationLog | None,
    recorded_at: datetime,
    duplicate: bool,
    route_point_saved: bool,
    client_point_id: str | None,
) -> dict[str, Any]:
    return {
        "live_location_id": live.pk,
        "route_point_saved": route_point_saved,
        "route_point_id": route_point.pk if route_point else None,
        "location_log_id": location_log.pk if location_log else None,
        "recorded_at": recorded_at.isoformat(),
        "duplicate": duplicate,
        "client_point_id": client_point_id,
        "duty_session_id": live.duty_session_id,
    }


def _find_existing_by_client_id(
    duty: DutySession, client_point_id: str
) -> EmployeeRoutePoint | None:
    return (
        EmployeeRoutePoint.objects.filter(
            duty_session=duty,
            client_point_id=client_point_id,
        )
        .order_by("id")
        .first()
    )


def _mirror_location_log(
    *,
    user: User,
    duty: DutySession,
    lat_dec: Decimal,
    lng_dec: Decimal,
    accuracy,
    speed,
    heading,
    battery,
    payload: dict[str, Any],
    recorded_at: datetime,
    device_model: str | None,
    app_version: str | None,
) -> LocationLog | None:
    if not duty.workday_id:
        return None
    return LocationLog.objects.create(
        user=user,
        workday_id=duty.workday_id,
        latitude=lat_dec,
        longitude=lng_dec,
        accuracy=accuracy,
        speed=speed,
        heading=heading,
        battery_level=battery,
        network_type=payload.get("network_type"),
        device_model=device_model or payload.get("device_model"),
        app_version=app_version or payload.get("app_version"),
        recorded_at=recorded_at,
    )


@transaction.atomic
def apply_gps_point(
    user: User,
    duty: DutySession,
    payload: dict[str, Any],
    *,
    device_model: str | None = None,
    app_version: str | None = None,
) -> dict[str, Any]:
    """
    Canonical single-point write.

    - Always updates EmployeeLiveLocation + GPS state.
    - Persists EmployeeRoutePoint when throttled OR client_point_id is present.
    - Idempotent on (duty_session, client_point_id).
    """
    _validate_duty_ownership(user, duty, payload)

    if "latitude" not in payload or "longitude" not in payload:
        raise GpsTrackingError("latitude and longitude are required", "VALIDATION_ERROR")

    try:
        lat, lng = validate_latitude_longitude(payload["latitude"], payload["longitude"])
    except Exception as exc:
        # DRF ValidationError or ValueError
        message = getattr(exc, "detail", None) or str(exc)
        if isinstance(message, (list, dict)):
            message = str(message)
        raise GpsTrackingError(str(message), "INVALID_COORDS") from exc

    try:
        recorded_at = parse_recorded_at(
            payload.get("recorded_at")
            or payload.get("captured_at")
            or payload.get("timestamp")
        )
    except GpsTrackingError:
        raise
    except Exception as exc:
        raise GpsTrackingError("Invalid recorded_at timestamp", "INVALID_TIMESTAMP") from exc

    _validate_recorded_at_within_duty(duty, recorded_at)

    client_point_id = extract_client_point_id(payload)
    accuracy = payload.get("accuracy")
    speed = payload.get("speed")
    heading = payload.get("heading")
    battery = payload.get("battery_level")
    lat_dec, lng_dec = _quantize(lat, lng)
    gps_defaults = gps_state_defaults_from_payload(payload)

    # Idempotent replay: return existing route point, still refresh live location.
    if client_point_id:
        existing = _find_existing_by_client_id(duty, client_point_id)
        if existing is not None:
            live, _ = EmployeeLiveLocation.objects.update_or_create(
                user=user,
                defaults={
                    "duty_session": duty,
                    "latitude": lat_dec,
                    "longitude": lng_dec,
                    "accuracy": accuracy,
                    "speed": speed,
                    "heading": heading,
                    "battery_level": battery,
                    "recorded_at": recorded_at,
                    **gps_defaults,
                },
            )
            upsert_employee_gps_state(
                user, payload, reported_at=recorded_at, sync_live_location=False
            )
            duty.last_heartbeat = timezone.now()
            duty.save(update_fields=["last_heartbeat"])
            if duty.workday_id:
                WorkDay.objects.filter(pk=duty.workday_id).update(
                    last_heartbeat=timezone.now()
                )
            return _serialize_point_result(
                live=live,
                route_point=existing,
                location_log=None,
                recorded_at=existing.recorded_at,
                duplicate=True,
                route_point_saved=False,
                client_point_id=client_point_id,
            )

    live, _created = EmployeeLiveLocation.objects.update_or_create(
        user=user,
        defaults={
            "duty_session": duty,
            "latitude": lat_dec,
            "longitude": lng_dec,
            "accuracy": accuracy,
            "speed": speed,
            "heading": heading,
            "battery_level": battery,
            "recorded_at": recorded_at,
            **gps_defaults,
        },
    )
    upsert_employee_gps_state(
        user, payload, reported_at=recorded_at, sync_live_location=False
    )

    # If Start Work Day had no GPS, backfill DutySession start coords once from
    # the first valid ping so Route History can emit a Start marker from duty.
    from tracking.duty_service import (
        _ensure_start_route_point,
        _persist_duty_start_coords,
    )

    if _persist_duty_start_coords(duty, lat, lng):
        duty.refresh_from_db(fields=["latitude", "longitude"])
        _ensure_start_route_point(user, duty, lat, lng)

    # Persist route point when client id present (offline) or throttle allows (live).
    force_save = bool(client_point_id)
    save_route = force_save or should_save_route_point(
        duty_session_id=duty.pk,
        latitude=lat,
        longitude=lng,
        recorded_at=recorded_at,
        force=False,
    )

    route_point = None
    location_log = None
    if save_route:
        try:
            with transaction.atomic():
                route_point = EmployeeRoutePoint.objects.create(
                    user=user,
                    duty_session=duty,
                    latitude=lat_dec,
                    longitude=lng_dec,
                    accuracy=accuracy,
                    speed=speed,
                    heading=heading,
                    recorded_at=recorded_at,
                    point_type=EmployeeRoutePoint.POINT_GPS,
                    client_point_id=client_point_id,
                )
        except IntegrityError:
            # Concurrent replay won the unique race — treat as duplicate.
            existing = (
                _find_existing_by_client_id(duty, client_point_id)
                if client_point_id
                else None
            )
            if existing is None:
                raise
            return _serialize_point_result(
                live=live,
                route_point=existing,
                location_log=None,
                recorded_at=existing.recorded_at,
                duplicate=True,
                route_point_saved=False,
                client_point_id=client_point_id,
            )

        location_log = _mirror_location_log(
            user=user,
            duty=duty,
            lat_dec=lat_dec,
            lng_dec=lng_dec,
            accuracy=accuracy,
            speed=speed,
            heading=heading,
            battery=battery,
            payload=payload,
            recorded_at=recorded_at,
            device_model=device_model,
            app_version=app_version,
        )

    if duty.workday_id:
        refresh_workday_live_state(
            user=user,
            workday=duty.workday,
            latitude=lat,
            longitude=lng,
            accuracy=accuracy,
            battery_level=battery,
            recorded_at=recorded_at,
        )
        WorkDay.objects.filter(pk=duty.workday_id).update(last_heartbeat=timezone.now())

    duty.last_heartbeat = timezone.now()
    duty.save(update_fields=["last_heartbeat"])

    return _serialize_point_result(
        live=live,
        route_point=route_point,
        location_log=location_log,
        recorded_at=recorded_at,
        duplicate=False,
        route_point_saved=bool(route_point),
        client_point_id=client_point_id,
    )


def get_active_duty_for_gps(user: User) -> DutySession:
    """Resolve active duty after lazy expiry; raise if none."""
    expire_overlong_workdays_for_user(user)
    from tracking.duty_service import get_active_duty

    duty = get_active_duty(user)
    if not duty or not duty.is_active:
        raise GpsTrackingError(WORKDAY_EXPIRED_MESSAGE, "NO_ACTIVE_DUTY")
    return duty


@transaction.atomic
def update_gps_point(
    user: User,
    payload: dict[str, Any],
    *,
    device_model: str | None = None,
    app_version: str | None = None,
) -> dict[str, Any]:
    """Public single-point entry: validates account + active duty, then applies."""
    _ensure_field_employee(user)
    duty = get_active_duty_for_gps(user)
    return apply_gps_point(
        user,
        duty,
        payload,
        device_model=device_model,
        app_version=app_version,
    )


def _bulk_sort_key(point: dict[str, Any]) -> datetime:
    try:
        return parse_recorded_at(
            point.get("recorded_at")
            or point.get("captured_at")
            or point.get("timestamp")
        )
    except GpsTrackingError:
        return timezone.now()


def bulk_update_gps_points(
    user: User,
    points: list[dict[str, Any]],
    *,
    device_model: str | None = None,
    app_version: str | None = None,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Offline/bulk sync through the same canonical writer."""
    _ensure_field_employee(user)
    duty = get_active_duty_for_gps(user)

    if len(points) > MAX_BULK_LOCATION_POINTS:
        raise GpsTrackingError(
            f"Max {MAX_BULK_LOCATION_POINTS} points per request",
            "BULK_LIMIT_EXCEEDED",
        )

    sorted_points = sorted(
        enumerate(points), key=lambda item: _bulk_sort_key(item[1])
    )
    request_meta = request_meta or {}

    success_count = 0
    failed_count = 0
    duplicate_count = 0
    failed_items: list[dict[str, Any]] = []
    accepted_ids: list[str] = []
    route_points_saved = 0

    for original_index, point in sorted_points:
        merged = {**request_meta, **point}
        client_point_id = extract_client_point_id(merged)
        try:
            with transaction.atomic():
                result = apply_gps_point(
                    user,
                    duty,
                    merged,
                    device_model=device_model,
                    app_version=app_version,
                )
            success_count += 1
            if client_point_id:
                accepted_ids.append(client_point_id)
            if result.get("duplicate"):
                duplicate_count += 1
            if result.get("route_point_saved"):
                route_points_saved += 1
        except GpsTrackingError as exc:
            failed_count += 1
            failed_items.append(
                {
                    "index": original_index,
                    "client_point_id": client_point_id,
                    "local_point_id": client_point_id,
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.code
                    in {"POINT_ERROR", "NO_ACTIVE_DUTY", "OUTSIDE_DUTY_WINDOW"},
                }
            )
        except (ValueError, TypeError) as exc:
            failed_count += 1
            failed_items.append(
                {
                    "index": original_index,
                    "client_point_id": client_point_id,
                    "local_point_id": client_point_id,
                    "code": "INVALID_POINT",
                    "message": str(exc),
                    "retryable": False,
                }
            )
        except Exception as exc:
            failed_count += 1
            failed_items.append(
                {
                    "index": original_index,
                    "client_point_id": client_point_id,
                    "local_point_id": client_point_id,
                    "code": "POINT_ERROR",
                    "message": str(exc),
                    "retryable": True,
                }
            )

    logger.info(
        "event=gps_bulk_sync user_id=%s duty_id=%s success=%s failed=%s "
        "duplicates=%s route_saved=%s",
        user.pk,
        duty.pk,
        success_count,
        failed_count,
        duplicate_count,
        route_points_saved,
    )
    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "duplicate_count": duplicate_count,
        "accepted_ids": accepted_ids,
        "failed_items": failed_items,
        "route_points_saved": route_points_saved,
        "duty_session_id": duty.pk,
        "workday_id": duty.workday_id,
    }


def generate_compat_client_point_id() -> str:
    """Server-generated id for legacy callers that omit client_point_id."""
    return f"compat-{uuid.uuid4()}"


def duty_start_client_point_id(duty_session_id: int) -> str:
    return f"duty-start:{duty_session_id}"


def duty_end_client_point_id(duty_session_id: int) -> str:
    return f"duty-end:{duty_session_id}"


def ensure_duty_boundary_point(
    *,
    user: User,
    duty: DutySession,
    latitude: float | None,
    longitude: float | None,
    point_type: str,
    client_point_id: str,
    recorded_at=None,
) -> EmployeeRoutePoint | None:
    """
    Create exactly one permanent start/end route point for a DutySession.

    Location is optional: missing/invalid coordinates return None without
    failing the duty lifecycle. Idempotent on (duty_session, client_point_id).
    """
    if latitude is None or longitude is None:
        return None
    try:
        validate_latitude_longitude(latitude, longitude)
    except Exception:
        logger.warning(
            "event=duty_boundary_point_invalid_coords duty_id=%s point_type=%s",
            duty.pk,
            point_type,
        )
        return None

    existing = (
        EmployeeRoutePoint.objects.filter(
            duty_session=duty, client_point_id=client_point_id
        )
        .order_by("id")
        .first()
    )
    if existing:
        return existing

    existing_type = (
        EmployeeRoutePoint.objects.filter(duty_session=duty, point_type=point_type)
        .order_by("id")
        .first()
    )
    if existing_type:
        return existing_type

    lat = Decimal(str(latitude)).quantize(Decimal("0.000001"))
    lng = Decimal(str(longitude)).quantize(Decimal("0.000001"))
    recorded_at = recorded_at or duty.start_time or timezone.now()

    try:
        with transaction.atomic():
            return EmployeeRoutePoint.objects.create(
                user=user,
                duty_session=duty,
                latitude=lat,
                longitude=lng,
                recorded_at=recorded_at,
                point_type=point_type,
                client_point_id=client_point_id,
                is_permanent=True,
            )
    except IntegrityError:
        return (
            EmployeeRoutePoint.objects.filter(
                duty_session=duty, client_point_id=client_point_id
            ).first()
            or EmployeeRoutePoint.objects.filter(
                duty_session=duty, point_type=point_type
            ).first()
        )
