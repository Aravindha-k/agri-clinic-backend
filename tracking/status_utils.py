"""Admin/mobile tracking status helpers (workday, GPS, movement).

9-hour timer arithmetic comes only from tracking.duty_timer.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from django.utils import timezone

from tracking.duty_timer import (
    compute_duty_timer,
    compute_session_timer,
    format_elapsed_label,
    resolve_duty_for_workday,
)
from tracking.models import LocationLog, WorkDay

# Heartbeat thresholds (minutes) — keep in sync with tracking.views
HEARTBEAT_STALE_MINUTES = 5

MOVEMENT_WINDOW_MINUTES = 10
MOVEMENT_MIN_DISTANCE_KM = 0.03  # ~30 m between last two points
MOVEMENT_MIN_SPEED_KMH = 2.0


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _timer_for_workday(
    workday: WorkDay | None,
    *,
    duty=None,
    timer: dict | None = None,
    now=None,
) -> dict | None:
    """Compute or reuse a single timer snapshot for a workday/duty pair."""
    if timer is not None:
        return timer
    now = now or timezone.now()
    duty = duty if duty is not None else resolve_duty_for_workday(workday)
    if duty is not None:
        return compute_duty_timer(duty, now=now)
    if workday is not None and workday.start_time:
        return compute_session_timer(
            start_time=workday.start_time,
            end_time=workday.end_time,
            is_active=bool(workday.is_active),
            auto_ended=bool(workday.auto_ended),
            session_id=None,
            now=now,
        )
    return None


def _is_active_within_limit(
    workday: WorkDay | None,
    *,
    duty=None,
    timer: dict | None = None,
    now=None,
) -> bool:
    now = now or timezone.now()
    t = _timer_for_workday(workday, duty=duty, timer=timer, now=now)
    if t is None:
        return False
    return bool(t.get("is_active")) and not bool(t.get("is_expired"))


def resolve_work_status(
    workday: WorkDay | None,
    *,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> str:
    """working | stopped | auto_ended"""
    if not workday:
        return "stopped"
    t = _timer_for_workday(workday, duty=duty, timer=timer, now=now)
    if t and t.get("is_active") and not t.get("is_expired"):
        return "working"
    if workday.auto_ended or (t and t.get("auto_ended")):
        return "auto_ended"
    return "stopped"


def _work_status_api(
    workday: WorkDay | None,
    *,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> str:
    """Legacy admin values: WORKING | NOT_WORKING | STOPPED."""
    status = resolve_work_status(workday, now=now, duty=duty, timer=timer)
    if status == "working":
        return "WORKING"
    return "NOT_WORKING"


def is_recently_online(
    workday: WorkDay | None,
    heartbeat_threshold,
    *,
    last_location_at=None,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> bool:
    if not _is_active_within_limit(workday, duty=duty, timer=timer, now=now):
        return False
    hb_ok = workday.last_heartbeat and workday.last_heartbeat >= heartbeat_threshold
    loc_ok = last_location_at and last_location_at >= heartbeat_threshold
    return bool(hb_ok or loc_ok)


def batch_movement_status_map(
    user_ids: list[int],
    active_workdays: dict[int, WorkDay],
    *,
    now=None,
    duty_by_user: dict | None = None,
    timer_by_user: dict | None = None,
) -> dict[int, str]:
    """Last-two-point movement for many users (single query)."""
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber

    now = now or timezone.now()
    duty_by_user = duty_by_user or {}
    timer_by_user = timer_by_user or {}
    result = {uid: "stopped" for uid in user_ids}
    working_ids = [
        uid
        for uid in user_ids
        if uid in active_workdays
        and _is_active_within_limit(
            active_workdays[uid],
            duty=duty_by_user.get(uid),
            timer=timer_by_user.get(uid),
            now=now,
        )
    ]
    if not working_ids:
        return result

    ranked = (
        LocationLog.objects.filter(user_id__in=working_ids)
        .annotate(
            rn=Window(
                expression=RowNumber(),
                partition_by=[F("user_id")],
                order_by=F("recorded_at").desc(),
            )
        )
        .filter(rn__lte=2)
        .values("user_id", "latitude", "longitude", "recorded_at")
    )
    points_by_user: dict[int, list] = {}
    for row in ranked:
        points_by_user.setdefault(row["user_id"], []).append(row)

    for uid in working_ids:
        points = sorted(
            points_by_user.get(uid, []),
            key=lambda p: p["recorded_at"],
            reverse=True,
        )
        if len(points) < 2:
            result[uid] = "idle"
            continue
        newer, older = points[0], points[1]
        dt = (newer["recorded_at"] - older["recorded_at"]).total_seconds()
        if dt <= 0 or dt > MOVEMENT_WINDOW_MINUTES * 60:
            result[uid] = "idle"
            continue
        dist = _distance_km(
            float(older["latitude"]),
            float(older["longitude"]),
            float(newer["latitude"]),
            float(newer["longitude"]),
        )
        speed_kmh = (dist / dt) * 3600 if dt else 0
        if dist >= MOVEMENT_MIN_DISTANCE_KM or speed_kmh >= MOVEMENT_MIN_SPEED_KMH:
            result[uid] = "moving"
        else:
            result[uid] = "idle"
    return result


def resolve_movement_status(
    user_id: int,
    workday: WorkDay | None,
    *,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> str:
    """moving | idle | stopped"""
    if not _is_active_within_limit(workday, duty=duty, timer=timer, now=now):
        return "stopped"

    points = list(
        LocationLog.objects.filter(user_id=user_id)
        .order_by("-recorded_at")
        .values("latitude", "longitude", "recorded_at")[:2]
    )
    if len(points) < 2:
        return "idle"

    newer, older = points[0], points[1]
    dt = (newer["recorded_at"] - older["recorded_at"]).total_seconds()
    if dt <= 0:
        return "idle"

    if dt > MOVEMENT_WINDOW_MINUTES * 60:
        return "idle"

    dist = _distance_km(
        float(older["latitude"]),
        float(older["longitude"]),
        float(newer["latitude"]),
        float(newer["longitude"]),
    )
    speed_kmh = (dist / dt) * 3600 if dt else 0
    if dist >= MOVEMENT_MIN_DISTANCE_KM or speed_kmh >= MOVEMENT_MIN_SPEED_KMH:
        return "moving"
    return "idle"


def resolve_workday_status(
    workday: WorkDay | None,
    *,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> str:
    """not_started | working | ended"""
    if not workday:
        return "not_started"
    if _is_active_within_limit(workday, duty=duty, timer=timer, now=now):
        return "working"
    if workday.end_time or workday.auto_ended or not workday.is_active:
        return "ended"
    return "not_started"


def resolve_gps_data_status(
    *,
    workday: WorkDay | None,
    last_location_at,
    points_today: int,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> str:
    """online | offline | never_sent"""
    now = now or timezone.now()
    active = _is_active_within_limit(workday, duty=duty, timer=timer, now=now)
    if not active:
        if points_today > 0:
            return "offline"
        return "never_sent"
    if points_today <= 0:
        return "never_sent"
    if not last_location_at:
        return "never_sent"
    heartbeat_threshold = now - timedelta(minutes=HEARTBEAT_STALE_MINUTES)
    if last_location_at >= heartbeat_threshold:
        return "online"
    return "offline"


def resolve_tracking_task_status(
    *,
    workday: WorkDay | None,
    gps_off: bool,
    tracking_status: str,
    points_today: int,
    now=None,
    duty=None,
    timer: dict | None = None,
) -> str:
    active = _is_active_within_limit(workday, duty=duty, timer=timer, now=now)
    if not active:
        return "stopped"
    if gps_off:
        return "stopped"
    if points_today <= 0:
        return "stopped"
    if tracking_status in ("online", "offline"):
        return "tracking" if tracking_status == "online" else "stopped"
    return "unknown"


def _location_age_minutes(last_location_at, *, now=None) -> int | None:
    if not last_location_at:
        return None
    now = now or timezone.now()
    try:
        return max(int((now - last_location_at).total_seconds() // 60), 0)
    except (TypeError, ValueError):
        return None


def build_admin_tracking_row(
    *,
    emp,
    user,
    workday: WorkDay | None,
    last_location: dict | None,
    gps_off: bool,
    now=None,
    request=None,
    movement_status: str | None = None,
    device_status: dict | None = None,
    points_today: int = 0,
    distance_km_today: float | None = None,
    duty=None,
    timer: dict | None = None,
) -> dict[str, Any]:
    """Standard admin tracking row; safe when workday/location is missing."""
    from utils.photo_urls import build_profile_photo_url

    now = now or timezone.now()
    heartbeat_threshold = now - timedelta(minutes=HEARTBEAT_STALE_MINUTES)

    district_name = None
    if emp.village and emp.village.district:
        district_name = emp.village.district.name

    photo_updated = getattr(emp, "profile_photo_updated_at", None)
    uid = emp.user_id

    last_seen = None
    last_lat = None
    last_lng = None
    last_loc_at = None
    last_speed = None
    last_accuracy = None
    last_battery = None
    if last_location:
        last_lat = float(last_location["latitude"])
        last_lng = float(last_location["longitude"])
        last_loc_at = last_location.get("recorded_at")
        last_seen = (
            last_loc_at.isoformat()
            if hasattr(last_loc_at, "isoformat")
            else str(last_loc_at)
        )
        last_speed = last_location.get("speed")
        last_accuracy = last_location.get("accuracy")
        last_battery = last_location.get("battery_level")

    # One timer computation per row
    if timer is None:
        duty = duty if duty is not None else resolve_duty_for_workday(workday)
        timer = _timer_for_workday(workday, duty=duty, now=now)

    online = is_recently_online(
        workday,
        heartbeat_threshold,
        last_location_at=last_loc_at,
        now=now,
        duty=duty,
        timer=timer,
    )
    if movement_status is None:
        movement_status = resolve_movement_status(
            uid, workday, now=now, duty=duty, timer=timer
        )
    work_status_internal = resolve_work_status(
        workday, now=now, duty=duty, timer=timer
    )
    work_status = _work_status_api(workday, now=now, duty=duty, timer=timer)

    active = _is_active_within_limit(workday, duty=duty, timer=timer, now=now)
    recent_location = bool(last_loc_at and last_loc_at >= heartbeat_threshold)

    if not active or work_status_internal == "stopped":
        tracking_status = "stopped"
    elif recent_location and active:
        tracking_status = "tracking"
    elif online:
        tracking_status = "online"
    else:
        tracking_status = "offline"

    if not active:
        gps_api, connection = "GPS_OFF", "OFFLINE"
        gps_conn = "offline"
    elif gps_off:
        gps_api, connection = "GPS_OFF", "OFFLINE"
        gps_conn = "offline"
    elif tracking_status in ("tracking", "online"):
        gps_api, connection = "GPS_ON", "ONLINE"
        gps_conn = "online"
    else:
        gps_api, connection = "GPS_OFF", "OFFLINE"
        gps_conn = "offline"

    workday_started_at = (
        (timer or {}).get("started_at")
        or (workday.start_time.isoformat() if workday and workday.start_time else None)
    )
    workday_ends_at = (timer or {}).get("expected_end_at")

    today_duration = None
    if workday and timer and (active or timer.get("elapsed_seconds")):
        today_duration = format_elapsed_label(timer["elapsed_seconds"])

    tracking_health = "STOPPED"
    if active and workday and workday.last_heartbeat:
        diff = (now - workday.last_heartbeat).total_seconds() / 60
        if diff <= HEARTBEAT_STALE_MINUTES:
            tracking_health = "OK"
        elif diff <= 15:
            tracking_health = "STALE"

    if device_status is None:
        from accounts.device_sessions import device_status_payload

        device_status = device_status_payload(user)

    workday_status = resolve_workday_status(
        workday, now=now, duty=duty, timer=timer
    )
    gps_data_status = resolve_gps_data_status(
        workday=workday,
        last_location_at=last_loc_at,
        points_today=points_today,
        now=now,
        duty=duty,
        timer=timer,
    )
    tracking_task_status = resolve_tracking_task_status(
        workday=workday,
        gps_off=gps_off,
        tracking_status=tracking_status,
        points_today=points_today,
        now=now,
        duty=duty,
        timer=timer,
    )
    last_location_age_minutes = _location_age_minutes(last_loc_at, now=now)
    last_location_at_iso = last_seen

    return {
        "user_id": uid,
        "employee_id": emp.employee_id,
        "device_status": device_status,
        "username": user.username or emp.employee_id,
        "employee_name": user.username or emp.employee_id,
        "phone": emp.phone or "",
        "profile_photo_url": build_profile_photo_url(request, emp.profile_photo)
        if request
        else None,
        "profile_photo_updated_at": (
            photo_updated.isoformat() if photo_updated else None
        ),
        "district": district_name,
        "work_status": work_status,
        "work_status_detail": work_status_internal,
        "connection": connection,
        "gps_status": gps_api,
        "gps_connection": gps_conn,
        "movement_status": movement_status,
        "tracking_status": tracking_status,
        "tracking_health": tracking_health,
        "last_seen": last_seen,
        "today_duration": today_duration,
        "last_latitude": last_lat,
        "last_longitude": last_lng,
        "last_location": (
            {"latitude": last_lat, "longitude": last_lng, "recorded_at": last_seen}
            if last_lat is not None
            else None
        ),
        "active_workday": active,
        "workday_id": workday.id if workday else None,
        "duty_session_id": (duty.id if duty is not None else (timer or {}).get("id")),
        "workday_started_at": workday_started_at,
        "workday_ends_at": workday_ends_at,
        "expected_end_at": workday_ends_at,
        "elapsed_seconds": (timer or {}).get("elapsed_seconds"),
        "remaining_seconds": (timer or {}).get("remaining_seconds"),
        "duration_limit_seconds": (timer or {}).get("duration_limit_seconds"),
        "server_now": (timer or {}).get("server_now"),
        "is_expired": (timer or {}).get("is_expired"),
        "completion_reason": (timer or {}).get("completion_reason"),
        "auto_ended": bool(workday.auto_ended) if workday else False,
        "is_online": online,
        "is_working": work_status == "WORKING",
        "workday_status": workday_status,
        "gps_data_status": gps_data_status,
        "tracking_task_status": tracking_task_status,
        "permission_status": "gps_off" if gps_off else "ok",
        "last_location_at": last_location_at_iso,
        "last_location_age_minutes": last_location_age_minutes,
        "total_points": points_today,
        "distance_km": distance_km_today,
        "today_distance_km": distance_km_today,
        "speed": last_speed,
        "accuracy": last_accuracy,
        "battery_level": last_battery,
    }
