"""Admin/mobile tracking status helpers (workday, GPS, movement)."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from django.utils import timezone

from .models import LocationLog, WorkDay
from .workday_utils import (
    MAX_WORKDAY_DURATION,
    is_workday_within_duration,
    workday_scheduled_end,
)

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


def resolve_work_status(workday: WorkDay | None, *, now=None) -> str:
    """
    working | stopped | auto_ended
    (uppercase WORKING / STOPPED / AUTO_ENDED for legacy admin UI)
    """
    if not workday:
        return "stopped"
    if workday.is_active and is_workday_within_duration(workday, now):
        return "working"
    if workday.auto_ended:
        return "auto_ended"
    return "stopped"


def _work_status_api(workday: WorkDay | None, *, now=None) -> str:
    """Legacy admin values: WORKING | NOT_WORKING | AUTO_ENDED | STOPPED."""
    status = resolve_work_status(workday, now=now)
    if status == "working":
        return "WORKING"
    if status == "auto_ended":
        return "AUTO_ENDED"
    return "NOT_WORKING"


def is_recently_online(
    workday: WorkDay | None,
    heartbeat_threshold,
    *,
    last_location_at=None,
    now=None,
) -> bool:
    if not workday or not is_workday_within_duration(workday, now):
        return False
    hb_ok = workday.last_heartbeat and workday.last_heartbeat >= heartbeat_threshold
    loc_ok = last_location_at and last_location_at >= heartbeat_threshold
    return bool(hb_ok or loc_ok)


def resolve_movement_status(
    user_id: int,
    workday: WorkDay | None,
    *,
    now=None,
) -> str:
    """moving | idle | stopped"""
    if not workday or not is_workday_within_duration(workday, now):
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


def build_admin_tracking_row(
    *,
    emp,
    user,
    workday: WorkDay | None,
    last_location: dict | None,
    gps_off: bool,
    now=None,
    request=None,
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
    if last_location:
        last_lat = float(last_location["latitude"])
        last_lng = float(last_location["longitude"])
        last_loc_at = last_location.get("recorded_at")
        last_seen = (
            last_loc_at.isoformat()
            if hasattr(last_loc_at, "isoformat")
            else str(last_loc_at)
        )

    online = is_recently_online(
        workday,
        heartbeat_threshold,
        last_location_at=last_loc_at,
        now=now,
    )
    movement_status = resolve_movement_status(uid, workday, now=now)
    work_status_internal = resolve_work_status(workday, now=now)
    work_status = _work_status_api(workday, now=now)

    active = workday is not None and is_workday_within_duration(workday, now)
    if not active:
        gps_api, connection = "GPS_OFF", "OFFLINE"
        gps_conn = "offline"
    elif gps_off:
        gps_api, connection = "GPS_OFF", "OFFLINE"
        gps_conn = "offline"
    elif online:
        gps_api, connection = "GPS_ON", "ONLINE"
        gps_conn = "online"
    else:
        gps_api, connection = "GPS_OFF", "OFFLINE"
        gps_conn = "offline"
    workday_started_at = workday.start_time.isoformat() if workday else None
    workday_ends_at = (
        workday_scheduled_end(workday.start_time).isoformat() if workday else None
    )

    today_duration = None
    if workday and active:
        end_ref = workday.end_time or now
        today_duration = _format_duration(end_ref - workday.start_time)

    tracking_health = "STOPPED"
    if active and workday.last_heartbeat:
        diff = (now - workday.last_heartbeat).total_seconds() / 60
        if diff <= HEARTBEAT_STALE_MINUTES:
            tracking_health = "OK"
        elif diff <= 15:
            tracking_health = "STALE"

    return {
        "user_id": uid,
        "employee_id": emp.employee_id,
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
        "workday_started_at": workday_started_at,
        "workday_ends_at": workday_ends_at,
        "auto_ended": bool(workday.auto_ended) if workday else False,
        "is_online": online,
        "is_working": work_status == "WORKING",
    }


def _format_duration(delta) -> str:
    total_seconds = max(int(delta.total_seconds()), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"
