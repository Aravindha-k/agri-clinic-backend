"""Duty session + live location + filtered route point business logic."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import EmployeeProfile
from tracking.models import (
    DutySession,
    EmployeeLiveLocation,
    EmployeeRoutePoint,
    LocationLog,
    WorkDay,
)
from tracking.gps_state import gps_state_defaults_from_payload, upsert_employee_gps_state
from tracking.route_point_filter import should_save_route_point
from tracking.services import refresh_workday_live_state
from tracking.workday_utils import (
    WORKDAY_EXPIRED_MESSAGE,
    clear_live_tracking_for_user,
    expire_overlong_workdays_for_user,
)
from utils.gps import validate_latitude_longitude

logger = logging.getLogger(__name__)

MAX_BULK_LOCATION_POINTS = 500


class DutyTrackingError(Exception):
    def __init__(self, message: str, code: str = "DUTY_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


def _ensure_field_employee(user: User) -> None:
    if user.is_staff:
        raise DutyTrackingError("Admins cannot use duty tracking", "FORBIDDEN")
    profile = EmployeeProfile.objects.filter(user=user).first()
    if profile and not profile.is_active_employee:
        raise DutyTrackingError("Inactive employee", "FORBIDDEN")


def get_active_duty(user: User) -> DutySession | None:
    expire_overlong_workdays_for_user(user)
    return (
        DutySession.objects.filter(user=user, is_active=True)
        .select_related("workday")
        .order_by("-start_time")
        .first()
    )


def _sync_workday_start(user: User, now, *, latitude=None, longitude=None) -> WorkDay:
    workday_kwargs = {
        "user": user,
        "date": now.date(),
        "start_time": now,
        "is_active": True,
        "last_heartbeat": now,
    }
    if latitude is not None and longitude is not None:
        workday_kwargs["latitude"] = latitude
        workday_kwargs["longitude"] = longitude
    return WorkDay.objects.create(**workday_kwargs)


@transaction.atomic
def start_duty(
    user: User,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> DutySession:
    _ensure_field_employee(user)
    expire_overlong_workdays_for_user(user)

    if DutySession.objects.filter(user=user, is_active=True).exists():
        raise DutyTrackingError("Duty already started", "DUTY_ALREADY_STARTED")

    now = timezone.now()
    lat_dec = lng_dec = None
    if latitude is not None and longitude is not None:
        validate_latitude_longitude(latitude, longitude)
        lat_dec = Decimal(str(latitude)).quantize(Decimal("0.000001"))
        lng_dec = Decimal(str(longitude)).quantize(Decimal("0.000001"))

    workday = _sync_workday_start(user, now, latitude=lat_dec, longitude=lng_dec)
    duty = DutySession.objects.create(
        user=user,
        workday=workday,
        date=now.date(),
        start_time=now,
        is_active=True,
        last_heartbeat=now,
        latitude=lat_dec,
        longitude=lng_dec,
    )
    logger.info("DutyStart user_id=%s duty_id=%s workday_id=%s", user.pk, duty.pk, workday.pk)
    return duty


@transaction.atomic
def end_duty(user: User) -> DutySession:
    _ensure_field_employee(user)
    expire_overlong_workdays_for_user(user)

    duty = get_active_duty(user)
    if not duty:
        raise DutyTrackingError("No active duty session", "NO_ACTIVE_DUTY")

    now = timezone.now()
    duty.end_time = now
    duty.is_active = False
    duty.save(update_fields=["end_time", "is_active"])

    if duty.workday_id:
        WorkDay.objects.filter(pk=duty.workday_id, is_active=True).update(
            end_time=now,
            is_active=False,
            auto_ended=False,
        )

    clear_live_tracking_for_user(user.pk)
    logger.info("DutyEnd user_id=%s duty_id=%s", user.pk, duty.pk)
    return duty


def _parse_recorded_at(raw) -> datetime:
    if raw is None:
        return timezone.now()
    if isinstance(raw, datetime):
        return raw if timezone.is_aware(raw) else timezone.make_aware(raw)
    if isinstance(raw, str):
        parsed = parse_datetime(raw.strip())
        if parsed is not None:
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    return timezone.now()


@transaction.atomic
def update_location(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_field_employee(user)
    expire_overlong_workdays_for_user(user)

    duty = get_active_duty(user)
    if not duty:
        raise DutyTrackingError(WORKDAY_EXPIRED_MESSAGE, "NO_ACTIVE_DUTY")

    return _apply_location_point(user, duty, payload)


def _validate_bulk_point_session(duty: DutySession, payload: dict[str, Any]) -> None:
    duty_session_id = payload.get("duty_session_id")
    workday_id = payload.get("workday_id")
    if duty_session_id not in (None, ""):
        if int(duty_session_id) != duty.pk:
            raise ValueError("duty_session_id does not match active duty session")
    if workday_id not in (None, ""):
        if duty.workday_id and int(workday_id) != duty.workday_id:
            raise ValueError("workday_id does not match active duty workday")


def _apply_location_point(
    user: User,
    duty: DutySession,
    payload: dict[str, Any],
    *,
    device_model: str | None = None,
    app_version: str | None = None,
) -> dict[str, Any]:
    """Apply one GPS fix: live location + throttled route point + legacy LocationLog."""
    if "latitude" not in payload or "longitude" not in payload:
        raise ValueError("latitude and longitude are required")

    _validate_bulk_point_session(duty, payload)

    lat = float(payload["latitude"])
    lng = float(payload["longitude"])
    validate_latitude_longitude(lat, lng)
    recorded_at = _parse_recorded_at(
        payload.get("recorded_at") or payload.get("captured_at") or payload.get("timestamp")
    )
    accuracy = payload.get("accuracy")
    speed = payload.get("speed")
    heading = payload.get("heading")
    battery = payload.get("battery_level")
    gps_defaults = gps_state_defaults_from_payload(payload)

    live, _created = EmployeeLiveLocation.objects.update_or_create(
        user=user,
        defaults={
            "duty_session": duty,
            "latitude": Decimal(str(lat)).quantize(Decimal("0.000001")),
            "longitude": Decimal(str(lng)).quantize(Decimal("0.000001")),
            "accuracy": accuracy,
            "speed": speed,
            "heading": heading,
            "battery_level": battery,
            "recorded_at": recorded_at,
            **gps_defaults,
        },
    )
    upsert_employee_gps_state(
        user,
        payload,
        reported_at=recorded_at,
        sync_live_location=False,
    )

    save_route = should_save_route_point(
        duty_session_id=duty.pk,
        latitude=lat,
        longitude=lng,
        recorded_at=recorded_at,
    )
    route_point = None
    location_log = None

    if save_route and duty.workday_id:
        route_point = EmployeeRoutePoint.objects.create(
            user=user,
            duty_session=duty,
            latitude=live.latitude,
            longitude=live.longitude,
            accuracy=accuracy,
            speed=speed,
            heading=heading,
            recorded_at=recorded_at,
            point_type=EmployeeRoutePoint.POINT_GPS,
        )
        location_log = LocationLog.objects.create(
            user=user,
            workday_id=duty.workday_id,
            latitude=live.latitude,
            longitude=live.longitude,
            accuracy=accuracy,
            speed=speed,
            heading=heading,
            battery_level=battery,
            network_type=payload.get("network_type"),
            device_model=device_model or payload.get("device_model"),
            app_version=app_version or payload.get("app_version"),
            recorded_at=recorded_at,
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

    return {
        "live_location_id": live.pk,
        "route_point_saved": save_route,
        "route_point_id": route_point.pk if route_point else None,
        "location_log_id": location_log.pk if location_log else None,
        "recorded_at": recorded_at.isoformat(),
    }


def _bulk_point_sort_key(point: dict[str, Any]) -> datetime:
    return _parse_recorded_at(
        point.get("recorded_at") or point.get("captured_at") or point.get("timestamp")
    )


def bulk_update_locations(
    user: User,
    points: list[dict[str, Any]],
    *,
    device_model: str | None = None,
    app_version: str | None = None,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Offline batch sync: per-point live update + throttled route points."""
    _ensure_field_employee(user)
    expire_overlong_workdays_for_user(user)

    duty = get_active_duty(user)
    if not duty:
        raise DutyTrackingError(WORKDAY_EXPIRED_MESSAGE, "NO_ACTIVE_DUTY")

    if len(points) > MAX_BULK_LOCATION_POINTS:
        raise DutyTrackingError(
            f"Max {MAX_BULK_LOCATION_POINTS} points per request",
            "BULK_LIMIT_EXCEEDED",
        )

    sorted_points = sorted(enumerate(points), key=lambda item: _bulk_point_sort_key(item[1]))
    request_meta = request_meta or {}

    success_count = 0
    failed_count = 0
    failed_items: list[dict[str, Any]] = []
    route_points_saved = 0

    for original_index, point in sorted_points:
        merged_point = {**request_meta, **point}
        try:
            with transaction.atomic():
                result = _apply_location_point(
                    user,
                    duty,
                    merged_point,
                    device_model=device_model,
                    app_version=app_version,
                )
            success_count += 1
            if result.get("route_point_saved"):
                route_points_saved += 1
        except (ValueError, TypeError) as exc:
            failed_count += 1
            failed_items.append(
                {
                    "index": original_index,
                    "code": "INVALID_POINT",
                    "message": str(exc),
                }
            )
        except Exception as exc:
            failed_count += 1
            failed_items.append(
                {
                    "index": original_index,
                    "code": "POINT_ERROR",
                    "message": str(exc),
                }
            )

    logger.info(
        "BulkLocationSync user_id=%s duty_id=%s success=%s failed=%s route_saved=%s",
        user.pk,
        duty.pk,
        success_count,
        failed_count,
        route_points_saved,
    )

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "failed_items": failed_items,
        "route_points_saved": route_points_saved,
        "duty_session_id": duty.pk,
        "workday_id": duty.workday_id,
    }


@transaction.atomic
def save_permanent_place_point(
    *,
    user: User,
    duty_session: DutySession | None,
    latitude: float,
    longitude: float,
    recorded_at: datetime | None = None,
    point_type: str,
    visit_id: int | None = None,
    farmer_id: int | None = None,
) -> EmployeeRoutePoint | None:
    """Persist visit/farmer location permanently on the route."""
    if duty_session is None:
        duty_session = get_active_duty(user)
    if duty_session is None:
        duty_session = (
            DutySession.objects.filter(user=user)
            .order_by("-start_time")
            .first()
        )
    if duty_session is None:
        return None

    validate_latitude_longitude(latitude, longitude)
    recorded_at = recorded_at or timezone.now()
    lat = Decimal(str(latitude)).quantize(Decimal("0.000001"))
    lng = Decimal(str(longitude)).quantize(Decimal("0.000001"))

    point = EmployeeRoutePoint.objects.create(
        user=user,
        duty_session=duty_session,
        latitude=lat,
        longitude=lng,
        recorded_at=recorded_at,
        point_type=point_type,
        visit_id=visit_id,
        farmer_id=farmer_id,
        is_permanent=True,
    )

    EmployeeLiveLocation.objects.update_or_create(
        user=user,
        defaults={
            "duty_session": duty_session,
            "latitude": lat,
            "longitude": lng,
            "recorded_at": recorded_at,
        },
    )
    return point


def get_route_points_for_date(user_id: int, target_date: date) -> list[EmployeeRoutePoint]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    end = start + timedelta(days=1)
    return list(
        EmployeeRoutePoint.objects.filter(
            user_id=user_id,
            recorded_at__gte=start,
            recorded_at__lt=end,
        ).order_by("recorded_at", "id")
    )


def serialize_route_point_model(point: EmployeeRoutePoint) -> dict[str, Any]:
    return {
        "id": point.id,
        "user_id": point.user_id,
        "duty_session_id": point.duty_session_id,
        "latitude": float(point.latitude),
        "longitude": float(point.longitude),
        "accuracy": point.accuracy,
        "speed": point.speed,
        "heading": point.heading,
        "recorded_at": point.recorded_at.isoformat(),
        "point_type": point.point_type,
        "visit_id": point.visit_id,
        "farmer_id": point.farmer_id,
        "is_permanent": point.is_permanent,
    }
