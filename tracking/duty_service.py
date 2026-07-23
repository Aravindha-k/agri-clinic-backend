"""Duty session + live location + filtered route point business logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
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
from tracking.duty_timer import (
    COMPLETION_MANUAL,
    compute_duty_timer,
    empty_duty_timer,
)
from tracking.duty_expiry import expire_overdue_duty_for_user
from utils.gps import validate_latitude_longitude

logger = logging.getLogger(__name__)

MAX_BULK_LOCATION_POINTS = 500


class DutyTrackingError(Exception):
    def __init__(self, message: str, code: str = "DUTY_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DutyStartResult:
    duty: DutySession
    created: bool


_ACTIVE_DUTY_CONSTRAINTS = {
    "uniq_active_duty_per_user",
    "uniq_active_workday_per_user",
}


def _is_active_duty_unique_violation(exc: IntegrityError) -> bool:
    """Recognize only the conditional uniques used by duty start."""
    cause = exc.__cause__
    constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
    if constraint_name:
        return constraint_name in _ACTIVE_DUTY_CONSTRAINTS

    # SQLite does not expose the constraint name. Keep this exact so unrelated
    # integrity failures cannot be mistaken for a concurrent duty start.
    message = str(exc)
    return message in {
        "UNIQUE constraint failed: tracking_dutysession.user_id",
        "UNIQUE constraint failed: tracking_workday.user_id",
    }


def _ensure_field_employee(user: User) -> None:
    if user.is_staff:
        raise DutyTrackingError("Admins cannot use duty tracking", "FORBIDDEN")
    profile = EmployeeProfile.objects.filter(user=user).first()
    if profile and not profile.is_active_employee:
        raise DutyTrackingError("Inactive employee", "FORBIDDEN")


def get_active_duty(user: User) -> DutySession | None:
    expire_overdue_duty_for_user(user, trigger="lazy_current")
    return (
        DutySession.objects.filter(user=user, is_active=True)
        .select_related("workday")
        .order_by("-start_time")
        .first()
    )


def _sync_workday_start(
    user: User,
    now,
    *,
    business_date: date | None = None,
    latitude=None,
    longitude=None,
) -> WorkDay:
    workday_kwargs = {
        "user": user,
        "date": business_date or timezone.localdate(),
        "start_time": now,
        "is_active": True,
        "last_heartbeat": now,
    }
    if latitude is not None and longitude is not None:
        workday_kwargs["latitude"] = latitude
        workday_kwargs["longitude"] = longitude
    return WorkDay.objects.create(**workday_kwargs)


def _lock_user(user: User) -> User:
    """Serialize duty lifecycle changes without locking nullable joined rows."""
    return User.objects.select_for_update().only("pk").get(pk=user.pk)


def _active_duty_for_locked_user(user: User) -> DutySession | None:
    return (
        DutySession.objects.filter(user=user, is_active=True)
        .select_related("workday")
        .order_by("-start_time")
        .first()
    )


@transaction.atomic
def start_duty(
    user: User,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> DutyStartResult:
    """
    Start a duty session and report whether this call created it.

    Guarantees one active DutySession per employee. Concurrent Start
    requests reuse the same session and started_at (never create a second).
    """
    _ensure_field_employee(user)
    user = _lock_user(user)
    expire_overdue_duty_for_user(user, trigger="lazy_start")

    existing = _active_duty_for_locked_user(user)
    if existing:
        logger.info(
            "DutyStart reuse user_id=%s duty_id=%s workday_id=%s",
            user.pk,
            existing.pk,
            existing.workday_id,
        )
        _persist_duty_start_coords(existing, latitude, longitude)
        _ensure_start_route_point(user, existing, latitude, longitude)
        return DutyStartResult(duty=existing, created=False)

    now = timezone.now()
    lat_dec = lng_dec = None
    if latitude is not None and longitude is not None:
        validate_latitude_longitude(latitude, longitude)
        lat_dec = Decimal(str(latitude)).quantize(Decimal("0.000001"))
        lng_dec = Decimal(str(longitude)).quantize(Decimal("0.000001"))
    else:
        logger.warning(
            "DutyStart missing_start_coords user_id=%s — "
            "Route History Start marker will be empty until coordinates are persisted",
            user.pk,
        )

    business_date = timezone.localdate()
    try:
        # Keep the create pair in a savepoint so a conditional-unique race does
        # not poison the outer transaction before we can return the winner.
        with transaction.atomic():
            workday = _sync_workday_start(
                user,
                now,
                business_date=business_date,
                latitude=lat_dec,
                longitude=lng_dec,
            )
            duty = DutySession.objects.create(
                user=user,
                workday=workday,
                date=business_date,
                start_time=now,
                is_active=True,
                last_heartbeat=now,
                latitude=lat_dec,
                longitude=lng_dec,
            )
    except IntegrityError as exc:
        if not _is_active_duty_unique_violation(exc):
            raise
        existing = _active_duty_for_locked_user(user)
        if existing is None:
            raise
        logger.info(
            "DutyStart unique-race reuse user_id=%s duty_id=%s workday_id=%s",
            user.pk,
            existing.pk,
            existing.workday_id,
        )
        _persist_duty_start_coords(existing, latitude, longitude)
        _ensure_start_route_point(user, existing, latitude, longitude)
        return DutyStartResult(duty=existing, created=False)
    logger.info(
        "DutyStart user_id=%s duty_id=%s workday_id=%s date=%s lat=%s lng=%s",
        user.pk,
        duty.pk,
        workday.pk,
        business_date,
        duty.latitude,
        duty.longitude,
    )
    _ensure_start_route_point(user, duty, latitude, longitude)
    return DutyStartResult(duty=duty, created=True)


def _persist_duty_start_coords(duty: DutySession, latitude, longitude) -> bool:
    """
    Persist Start Work Day coordinates onto DutySession + WorkDay once.

    Never overwrites an existing start position. Returns True when coords were
    written on this call.
    """
    if latitude is None or longitude is None:
        return False
    if duty.latitude is not None and duty.longitude is not None:
        return False
    try:
        validate_latitude_longitude(latitude, longitude)
    except Exception:
        logger.warning(
            "event=duty_start_coords_invalid duty_id=%s user_id=%s",
            duty.pk,
            duty.user_id,
        )
        return False

    lat_dec = Decimal(str(latitude)).quantize(Decimal("0.000001"))
    lng_dec = Decimal(str(longitude)).quantize(Decimal("0.000001"))
    duty.latitude = lat_dec
    duty.longitude = lng_dec
    duty.save(update_fields=["latitude", "longitude"])
    if duty.workday_id:
        WorkDay.objects.filter(pk=duty.workday_id, latitude__isnull=True).update(
            latitude=lat_dec,
            longitude=lng_dec,
        )
    logger.info(
        "event=duty_start_coords_persisted duty_id=%s lat=%s lng=%s",
        duty.pk,
        lat_dec,
        lng_dec,
    )
    return True


def _resolve_duty_start_coords(duty, latitude, longitude):
    """Prefer request coords; fall back to duty start lat/lng."""
    lat = latitude
    lng = longitude
    if lat is None and duty.latitude is not None:
        lat = float(duty.latitude)
    if lng is None and duty.longitude is not None:
        lng = float(duty.longitude)
    return lat, lng


def _sync_live_location_on_duty_start(user, duty, latitude, longitude) -> None:
    """
    Upsert EmployeeLiveLocation so admin Live Tracking reflects Start Work Day
    immediately (coords optional → NO_LOCATION_YET until first GPS).
    """
    from tracking.live_tracking_service import ensure_live_row_for_duty

    now = timezone.now()
    lat, lng = _resolve_duty_start_coords(duty, latitude, longitude)
    live = ensure_live_row_for_duty(user, duty)

    if lat is None or lng is None:
        EmployeeLiveLocation.objects.filter(pk=live.pk).update(
            duty_session=duty,
            last_heartbeat_at=now,
        )
        return

    try:
        validate_latitude_longitude(lat, lng)
    except Exception:
        logger.warning(
            "event=duty_start_live_invalid_coords user_id=%s duty_id=%s",
            user.pk,
            duty.pk,
        )
        EmployeeLiveLocation.objects.filter(pk=live.pk).update(
            duty_session=duty,
            last_heartbeat_at=now,
        )
        return

    lat_dec = Decimal(str(lat)).quantize(Decimal("0.000001"))
    lng_dec = Decimal(str(lng)).quantize(Decimal("0.000001"))
    EmployeeLiveLocation.objects.filter(pk=live.pk).update(
        duty_session=duty,
        latitude=lat_dec,
        longitude=lng_dec,
        recorded_at=now,
        last_heartbeat_at=now,
    )
    if duty.workday_id:
        workday = duty.workday
        if workday is None:
            workday = WorkDay.objects.filter(pk=duty.workday_id).first()
        if workday is not None:
            refresh_workday_live_state(
                user=user,
                workday=workday,
                latitude=float(lat_dec),
                longitude=float(lng_dec),
                recorded_at=now,
            )


def _ensure_start_route_point(user, duty, latitude, longitude) -> None:
    """Optional WORKDAY_START point. Missing coords do not fail duty start."""
    from tracking.gps_service import (
        duty_start_client_point_id,
        ensure_duty_boundary_point,
    )
    from tracking.models import EmployeeRoutePoint

    _persist_duty_start_coords(duty, latitude, longitude)
    duty.refresh_from_db(fields=["latitude", "longitude"])
    lat, lng = _resolve_duty_start_coords(duty, latitude, longitude)
    point = ensure_duty_boundary_point(
        user=user,
        duty=duty,
        latitude=lat,
        longitude=lng,
        point_type=EmployeeRoutePoint.POINT_START,
        client_point_id=duty_start_client_point_id(duty.pk),
        recorded_at=duty.start_time,
    )
    if point:
        logger.info(
            "event=duty_start_route_point duty_id=%s point_id=%s",
            duty.pk,
            point.pk,
        )
    elif lat is None or lng is None:
        logger.warning(
            "event=duty_start_route_point_skipped_no_coords duty_id=%s user_id=%s",
            duty.pk,
            user.pk,
        )
    _sync_live_location_on_duty_start(user, duty, latitude, longitude)


def _ensure_end_route_point(user, duty, latitude, longitude) -> None:
    """Optional WORKDAY_END point for manual end only."""
    from tracking.gps_service import (
        duty_end_client_point_id,
        ensure_duty_boundary_point,
    )
    from tracking.models import EmployeeRoutePoint

    point = ensure_duty_boundary_point(
        user=user,
        duty=duty,
        latitude=latitude,
        longitude=longitude,
        point_type=EmployeeRoutePoint.POINT_END,
        client_point_id=duty_end_client_point_id(duty.pk),
        recorded_at=duty.end_time or timezone.now(),
    )
    if point:
        logger.info(
            "event=duty_end_route_point duty_id=%s point_id=%s",
            duty.pk,
            point.pk,
        )


def serialize_duty_status(user: User, duty: DutySession | None = None) -> dict[str, Any]:
    """Canonical current-duty payload including 9-hour timer fields."""
    now = timezone.now()
    today = timezone.localdate()

    if duty is not None and duty.is_active:
        expire_overdue_duty_for_user(user, now=now, trigger="lazy_current")
        duty = (
            DutySession.objects.filter(pk=duty.pk)
            .select_related("workday")
            .first()
        )

    if duty is None:
        finalized = expire_overdue_duty_for_user(
            user, now=now, trigger="lazy_current"
        )
        active = (
            DutySession.objects.filter(user=user, is_active=True)
            .select_related("workday")
            .order_by("-start_time")
            .first()
        )
        if active:
            duty = active
        elif finalized is not None and not finalized.is_active:
            duty = (
                DutySession.objects.filter(pk=finalized.pk)
                .select_related("workday")
                .first()
            )
        else:
            duty = (
                DutySession.objects.filter(user=user, is_active=False)
                .select_related("workday")
                .order_by("-end_time", "-start_time")
                .first()
            )
            if duty and duty.end_time:
                if timezone.localtime(duty.end_time).date() != today:
                    duty = None
            elif duty and duty.date != today:
                duty = None

    if duty is None:
        empty = empty_duty_timer(now=now)
        return {
            **empty,
            "status": "not_started",  # legacy alias
            "duty_status": "NOT_STARTED",
            "user_id": user.pk,
            "duty_session_id": None,
            "workday_id": None,
            "latitude": None,
            "longitude": None,
            "work_date": today.isoformat(),
            "date": today.isoformat(),
            "end_work_time": None,
            "total_work_duration_ms": None,
            "server_time": empty["server_now"],
            "last_heartbeat": None,
        }

    timer = compute_duty_timer(duty, now=now)
    workday = duty.workday
    work_date = duty.date or (workday.date if workday else today)
    started = duty.start_time
    ended = duty.end_time
    duration_ms = None
    if started and ended:
        duration_ms = int(max(0, (ended - started).total_seconds() * 1000))

    if duty.is_active:
        legacy_status = "in_progress"
    elif duty.auto_ended:
        legacy_status = "completed"  # keep completed; timer.is_expired / duty_status show auto
    else:
        legacy_status = "completed"

    return {
        **timer,
        # Compatible aliases
        "status": legacy_status,
        "duty_status": timer["status"],
        "user_id": user.pk,
        "duty_session_id": duty.id,
        "workday_id": duty.workday_id or (workday.id if workday else None),
        "latitude": float(duty.latitude) if duty.latitude is not None else None,
        "longitude": float(duty.longitude) if duty.longitude is not None else None,
        "work_date": work_date.isoformat() if work_date else None,
        "date": work_date.isoformat() if work_date else None,
        "end_work_time": ended.isoformat() if ended else None,
        "total_work_duration_ms": duration_ms if not duty.is_active else None,
        "server_time": timer["server_now"],
        "last_heartbeat": (
            duty.last_heartbeat.isoformat() if duty.last_heartbeat else None
        ),
    }


@transaction.atomic
def end_duty(
    user: User,
    *,
    expected_duty_session_id: int | str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> DutySession:
    """
    Manually complete an active duty, or return the already-completed session.

    If the duty is past the 9-hour deadline, canonical auto-expiry wins:
    ended_at stays expected_end_at and completion_reason stays AUTO_EXPIRED.
    End coordinates are optional; auto-expiry never fabricates a GPS point.
    """
    from tracking.duty_expiry import complete_duty_as_auto_expired
    from tracking.duty_timer import is_duty_overdue

    _ensure_field_employee(user)
    user = _lock_user(user)
    now = timezone.now()

    expected_id = None
    if expected_duty_session_id not in (None, ""):
        try:
            expected_id = int(expected_duty_session_id)
        except (TypeError, ValueError) as exc:
            raise DutyTrackingError(
                "Invalid duty_session_id",
                "INVALID_DUTY_SESSION_ID",
            ) from exc

    if expected_id is not None:
        duty = (
            DutySession.objects.select_for_update()
            .filter(user=user, pk=expected_id)
            .first()
        )
        if duty is None:
            raise DutyTrackingError(
                "Duty session not found",
                "DUTY_SESSION_NOT_FOUND",
            )
        if not duty.is_active:
            logger.info("DutyEnd idempotent user_id=%s duty_id=%s", user.pk, duty.pk)
            _ensure_end_route_point(user, duty, latitude, longitude)
            return duty
    else:
        duty = (
            DutySession.objects.select_for_update()
            .filter(user=user, is_active=True)
            .order_by("-start_time")
            .first()
        )

    if not duty:
        last = (
            DutySession.objects.filter(user=user)
            .order_by("-start_time")
            .first()
        )
        if last and not last.is_active:
            logger.info("DutyEnd idempotent user_id=%s duty_id=%s", user.pk, last.pk)
            _ensure_end_route_point(user, last, latitude, longitude)
            return last
        raise DutyTrackingError("No active duty session", "NO_ACTIVE_DUTY")

    # Past deadline → auto-complete; do not overwrite with a later manual time.
    # Auto-expiry does not invent end GPS coordinates.
    if is_duty_overdue(duty, now=now):
        return complete_duty_as_auto_expired(
            duty, now=now, trigger="lazy_manual_end"
        )

    if latitude is not None and longitude is not None:
        validate_latitude_longitude(latitude, longitude)

    duty.end_time = now
    duty.is_active = False
    duty.auto_ended = False
    duty.completion_reason = COMPLETION_MANUAL
    duty.save(
        update_fields=[
            "end_time",
            "is_active",
            "auto_ended",
            "completion_reason",
        ]
    )

    if duty.workday_id:
        WorkDay.objects.filter(pk=duty.workday_id).update(
            end_time=now,
            is_active=False,
            auto_ended=False,
        )

    _ensure_end_route_point(user, duty, latitude, longitude)
    from tracking.live_tracking_service import finalize_live_state_on_duty_end

    finalize_live_state_on_duty_end(user, duty)
    clear_live_tracking_for_user(user.pk)
    logger.info(
        "event=duty_manual_completed user_id=%s duty_id=%s end_time=%s",
        user.pk,
        duty.pk,
        now.isoformat(),
    )
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


def update_location(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper → tracking.gps_service (canonical GPS writer)."""
    from tracking.gps_service import GpsTrackingError, update_gps_point

    try:
        return update_gps_point(user, payload)
    except GpsTrackingError as exc:
        raise DutyTrackingError(exc.message, exc.code) from exc


def bulk_update_locations(
    user: User,
    points: list[dict[str, Any]],
    *,
    device_model: str | None = None,
    app_version: str | None = None,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper → tracking.gps_service.bulk_update_gps_points."""
    from tracking.gps_service import GpsTrackingError, bulk_update_gps_points

    try:
        return bulk_update_gps_points(
            user,
            points,
            device_model=device_model,
            app_version=app_version,
            request_meta=request_meta,
        )
    except GpsTrackingError as exc:
        raise DutyTrackingError(exc.message, exc.code) from exc


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
        "client_point_id": point.client_point_id,
    }
