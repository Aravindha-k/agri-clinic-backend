"""
Canonical DutySession day-map builder.

ONE production builder for workday map payloads consumed by mobile and web.
Views must not assemble map data independently.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, time, timedelta
from typing import Any

from django.contrib.auth.models import User
from django.utils import timezone

from tracking.duty_service import serialize_duty_status
from tracking.models import DutySession, EmployeeLiveLocation, EmployeeRoutePoint, LocationLog
from tracking.route_utils import compute_route_distance_km, is_valid_coordinate
from visits.models import Visit
from visits.submitted import submitted_visits_qs

logger = logging.getLogger(__name__)

ROUTE_POINT_LIMIT = 5000
ROUTE_SOURCE_CANONICAL = "CANONICAL"
ROUTE_SOURCE_LEGACY = "LEGACY_FALLBACK"
DISTANCE_SOURCE_HAVERSINE = "HAVERSINE"
DISTANCE_SOURCE_CANONICAL = "CANONICAL"

# Semantic sources exposed in the API (map from EmployeeRoutePoint.point_type).
SOURCE_FOREGROUND = "FOREGROUND_TRACKING"
SOURCE_VISIT = "VISIT"
SOURCE_FARMER = "FARMER"
SOURCE_WORKDAY_START = "WORKDAY_START"
SOURCE_WORKDAY_END = "WORKDAY_END"
SOURCE_DUTY_START = "DUTY_START"
SOURCE_EARLIEST_FALLBACK = "EARLIEST_ROUTE_POINT"
SOURCE_LAST_FALLBACK = "LAST_ROUTE_POINT_INFERRED"
SOURCE_LEGACY_LOG = "LEGACY_LOCATION_LOG"

# Stored point_type values treated as start/end markers (max_length=10 on model).
POINT_TYPE_START = "start"
POINT_TYPE_END = "end"


class DayMapError(Exception):
    def __init__(self, message: str, *, code: str = "DAY_MAP_ERROR", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _valid_pair(lat: Any, lng: Any) -> tuple[float, float] | None:
    lat_f = _safe_float(lat)
    lng_f = _safe_float(lng)
    if lat_f is None or lng_f is None:
        return None
    if not is_valid_coordinate(lat_f, lng_f):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
        return None
    return lat_f, lng_f


def _point_source(point: EmployeeRoutePoint | dict) -> str:
    if isinstance(point, dict):
        ptype = (point.get("point_type") or point.get("source") or "").lower()
        client_id = point.get("client_point_id") or ""
        visit_id = point.get("visit_id")
    else:
        ptype = (point.point_type or "").lower()
        client_id = point.client_point_id or ""
        visit_id = point.visit_id

    if ptype == POINT_TYPE_START or str(client_id).startswith(
        ("duty-start:", "duty_start:")
    ):
        return SOURCE_WORKDAY_START
    if ptype == POINT_TYPE_END or str(client_id).startswith(
        ("duty-end:", "duty_end:")
    ):
        return SOURCE_WORKDAY_END
    if ptype == EmployeeRoutePoint.POINT_VISIT or visit_id:
        return SOURCE_VISIT
    if ptype == EmployeeRoutePoint.POINT_FARMER:
        return SOURCE_FARMER
    return SOURCE_FOREGROUND


def _marker(
    *,
    marker_id: str | int | None,
    latitude: float,
    longitude: float,
    captured_at: str | None,
    source: str,
    accuracy: float | None = None,
    inferred: bool = False,
) -> dict[str, Any]:
    return {
        "id": marker_id,
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": accuracy,
        "captured_at": captured_at,
        "source": source,
        "inferred": inferred,
    }


def _sample_route_points(
    points: list[dict[str, Any]],
    *,
    limit: int = ROUTE_POINT_LIMIT,
) -> tuple[list[dict[str, Any]], bool]:
    """Deterministic sample; always keep first, last, start/end/visit points."""
    if len(points) <= limit:
        return points, False

    must_keep: set[int] = set()
    if points:
        must_keep.add(0)
        must_keep.add(len(points) - 1)
    for idx, p in enumerate(points):
        src = p.get("source") or ""
        if src in {SOURCE_WORKDAY_START, SOURCE_WORKDAY_END, SOURCE_VISIT}:
            must_keep.add(idx)
        if p.get("visit_id"):
            must_keep.add(idx)

    remaining_slots = max(0, limit - len(must_keep))
    other_indices = [i for i in range(len(points)) if i not in must_keep]
    if remaining_slots and other_indices:
        if len(other_indices) <= remaining_slots:
            selected = set(other_indices)
        else:
            step = (len(other_indices) - 1) / max(remaining_slots - 1, 1)
            selected = set()
            for i in range(remaining_slots):
                selected.add(other_indices[int(round(i * step))])
        must_keep |= selected

    ordered = sorted(must_keep)
    sampled = [points[i] for i in ordered]
    # Re-sequence after sampling
    for seq, row in enumerate(sampled, start=1):
        row["sequence"] = seq
    return sampled, True


def _compute_bounds(coords: list[tuple[float, float]]) -> dict[str, float | None]:
    if not coords:
        return {
            "min_latitude": None,
            "max_latitude": None,
            "min_longitude": None,
            "max_longitude": None,
            "center_latitude": None,
            "center_longitude": None,
        }
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    return {
        "min_latitude": min_lat,
        "max_latitude": max_lat,
        "min_longitude": min_lng,
        "max_longitude": max_lng,
        "center_latitude": (min_lat + max_lat) / 2.0,
        "center_longitude": (min_lng + max_lng) / 2.0,
    }


def _load_canonical_route_points(duty: DutySession) -> list[EmployeeRoutePoint]:
    return list(
        EmployeeRoutePoint.objects.filter(duty_session_id=duty.pk)
        .order_by("recorded_at", "id")
        .only(
            "id",
            "latitude",
            "longitude",
            "accuracy",
            "recorded_at",
            "created_at",
            "point_type",
            "client_point_id",
            "visit_id",
            "farmer_id",
            "is_permanent",
            "duty_session_id",
            "user_id",
        )
    )


def _legacy_location_log_points(duty: DutySession) -> list[dict[str, Any]]:
    """Compatibility fallback when no EmployeeRoutePoint rows exist."""
    logger.warning(
        "day_map_legacy_fallback=true duty_session_id=%s user_id=%s",
        duty.pk,
        duty.user_id,
    )
    qs = LocationLog.objects.filter(user_id=duty.user_id)
    if duty.workday_id:
        qs = qs.filter(workday_id=duty.workday_id)
    else:
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(duty.date, time.min), tz)
        end = start + timedelta(days=1)
        qs = qs.filter(recorded_at__gte=start, recorded_at__lt=end)
    rows = list(
        qs.order_by("recorded_at", "id").only(
            "id", "latitude", "longitude", "accuracy", "recorded_at", "created_at"
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        pair = _valid_pair(row.latitude, row.longitude)
        if not pair:
            continue
        out.append(
            {
                "id": row.id,
                "latitude": pair[0],
                "longitude": pair[1],
                "accuracy": row.accuracy,
                "captured_at": row.recorded_at.isoformat() if row.recorded_at else None,
                "received_at": (
                    row.created_at.isoformat()
                    if getattr(row, "created_at", None)
                    else None
                ),
                "source": SOURCE_LEGACY_LOG,
                "point_type": "legacy",
                "visit_id": None,
                "client_point_id": None,
            }
        )
    return out


def _serialize_route_rows(
    points: list[EmployeeRoutePoint],
    *,
    invalid_skipped: list[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in points:
        pair = _valid_pair(point.latitude, point.longitude)
        if not pair:
            invalid_skipped.append(point.pk)
            logger.warning(
                "day_map_invalid_route_point id=%s duty_session_id=%s",
                point.pk,
                point.duty_session_id,
            )
            continue
        rows.append(
            {
                "id": point.id,
                "latitude": pair[0],
                "longitude": pair[1],
                "accuracy": point.accuracy,
                "captured_at": point.recorded_at.isoformat() if point.recorded_at else None,
                "received_at": point.created_at.isoformat() if point.created_at else None,
                "source": _point_source(point),
                "point_type": point.point_type,
                "visit_id": point.visit_id,
                "client_point_id": point.client_point_id,
            }
        )
    for seq, row in enumerate(rows, start=1):
        row["sequence"] = seq
    return rows


def _resolve_start_marker(
    duty: DutySession,
    route_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    # Prefer explicit WORKDAY_START route point over duty lat/lng or inference.
    for row in route_rows:
        if row.get("source") == SOURCE_WORKDAY_START:
            return _marker(
                marker_id=row.get("id"),
                latitude=row["latitude"],
                longitude=row["longitude"],
                captured_at=row.get("captured_at"),
                source=SOURCE_WORKDAY_START,
                accuracy=row.get("accuracy"),
                inferred=False,
            )
    pair = _valid_pair(duty.latitude, duty.longitude)
    if pair:
        return _marker(
            marker_id=f"duty-start:{duty.pk}",
            latitude=pair[0],
            longitude=pair[1],
            captured_at=duty.start_time.isoformat() if duty.start_time else None,
            source=SOURCE_DUTY_START,
            inferred=False,
        )
    if route_rows:
        row = route_rows[0]
        return _marker(
            marker_id=row.get("id"),
            latitude=row["latitude"],
            longitude=row["longitude"],
            captured_at=row.get("captured_at"),
            source=SOURCE_EARLIEST_FALLBACK,
            accuracy=row.get("accuracy"),
            inferred=True,
        )
    return None


def _resolve_end_marker(
    duty: DutySession,
    route_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if duty.is_active:
        return None
    for row in reversed(route_rows):
        if row.get("source") == SOURCE_WORKDAY_END:
            return _marker(
                marker_id=row.get("id"),
                latitude=row["latitude"],
                longitude=row["longitude"],
                captured_at=row.get("captured_at"),
                source=SOURCE_WORKDAY_END,
                accuracy=row.get("accuracy"),
                inferred=False,
            )
    if route_rows:
        row = route_rows[-1]
        return _marker(
            marker_id=row.get("id"),
            latitude=row["latitude"],
            longitude=row["longitude"],
            captured_at=row.get("captured_at"),
            source=SOURCE_LAST_FALLBACK,
            accuracy=row.get("accuracy"),
            inferred=True,
        )
    return None


def _load_visits_for_duty(duty: DutySession) -> list[Visit]:
    return list(
        submitted_visits_qs()
        .filter(duty_session_id=duty.pk)
        .select_related("farmer", "village")
        .order_by("visit_date", "visit_time", "created_at", "id")
    )


def _build_visit_markers(
    visits: list[Visit],
    route_rows: list[dict[str, Any]],
    *,
    invalid_skipped: list[int],
) -> tuple[list[dict[str, Any]], int]:
    """One Visit → one marker. Prefer VISIT route point coords."""
    visit_route: dict[int, dict[str, Any]] = {}
    for row in route_rows:
        vid = row.get("visit_id")
        if vid and row.get("source") == SOURCE_VISIT:
            visit_route.setdefault(int(vid), row)

    markers: list[dict[str, Any]] = []
    missing_coords = 0
    for visit in visits:
        lat = lng = None
        route_point_id = None
        rp = visit_route.get(visit.pk)
        if rp:
            lat, lng = rp["latitude"], rp["longitude"]
            route_point_id = rp.get("id")
        else:
            pair = _valid_pair(visit.latitude, visit.longitude)
            if pair:
                lat, lng = pair
            else:
                if visit.latitude is not None or visit.longitude is not None:
                    invalid_skipped.append(visit.pk)
                    logger.warning(
                        "day_map_invalid_visit_coords visit_id=%s", visit.pk
                    )
                missing_coords += 1
                continue

        visited_at = None
        if visit.visit_date and visit.visit_time:
            visited_at = f"{visit.visit_date.isoformat()}T{visit.visit_time.isoformat()}"
        elif visit.visit_date:
            visited_at = visit.visit_date.isoformat()
        elif visit.created_at:
            visited_at = visit.created_at.isoformat()

        farmer_name = visit.farmer_name
        farmer_phone = visit.farmer_phone
        if visit.farmer_id:
            farmer_name = farmer_name or visit.farmer.name
            farmer_phone = farmer_phone or visit.farmer.phone

        markers.append(
            {
                "visit_id": visit.pk,
                "sequence": 0,  # filled below
                "farmer_id": visit.farmer_id,
                "farmer_name": farmer_name or "",
                "farmer_phone": farmer_phone or "",
                "status": visit.status or "completed",
                "visited_at": visited_at,
                "latitude": lat,
                "longitude": lng,
                "route_point_id": route_point_id,
                "sync_status": "SYNCED",
            }
        )

    for seq, m in enumerate(markers, start=1):
        m["sequence"] = seq
    return markers, missing_coords


def _duty_block_from_serialize(timer_payload: dict[str, Any], duty: DutySession) -> dict[str, Any]:
    """Map serialize_duty_status fields into the day-map duty contract."""
    return {
        "id": duty.pk,
        "employee_id": duty.user_id,
        "status": timer_payload.get("duty_status") or timer_payload.get("status"),
        "completion_reason": duty.completion_reason,
        "start_time": timer_payload.get("started_at") or (
            duty.start_time.isoformat() if duty.start_time else None
        ),
        "ended_at": timer_payload.get("ended_at") or (
            duty.end_time.isoformat() if duty.end_time else None
        ),
        "duration_limit_seconds": timer_payload.get("duration_limit_seconds"),
        "expected_end_at": timer_payload.get("expected_end_at"),
        "server_now": timer_payload.get("server_now") or timer_payload.get("server_time"),
        "elapsed_seconds": timer_payload.get("elapsed_seconds"),
        "remaining_seconds": timer_payload.get("remaining_seconds"),
        "is_expired": timer_payload.get("is_expired"),
        # Compatibility aliases from serialize_duty_status
        "duty_session_id": duty.pk,
        "workday_id": duty.workday_id,
        "duty_status": timer_payload.get("duty_status"),
        "auto_ended": duty.auto_ended,
        "is_active": duty.is_active,
        "date": str(duty.date) if duty.date else None,
    }


def build_duty_day_map(
    duty: DutySession,
    *,
    viewer: User | None = None,
    include_live_location: bool = True,
) -> dict[str, Any]:
    """
    Canonical day-map payload for one DutySession.

    Route points may include VISIT points for continuity; visit_markers is the
    semantic marker layer (one Visit → one marker). Clients must not treat
    route_points as marker definitions.
    """
    invalid_skipped: list[int] = []

    # Timer — no local arithmetic
    timer_payload = serialize_duty_status(duty.user, duty)
    # Re-fetch duty after possible lazy expiry on active sessions
    duty = (
        DutySession.objects.select_related("user", "workday")
        .filter(pk=duty.pk)
        .first()
        or duty
    )

    canonical = _load_canonical_route_points(duty)
    if canonical:
        route_source = ROUTE_SOURCE_CANONICAL
        route_rows = _serialize_route_rows(canonical, invalid_skipped=invalid_skipped)
    else:
        route_source = ROUTE_SOURCE_LEGACY
        legacy = _legacy_location_log_points(duty)
        route_rows = []
        for seq, row in enumerate(legacy, start=1):
            row["sequence"] = seq
            route_rows.append(row)

    route_total = len(route_rows)
    route_rows, sampled = _sample_route_points(route_rows)

    visits = _load_visits_for_duty(duty)
    visit_markers, visits_missing_coords = _build_visit_markers(
        visits, route_rows, invalid_skipped=invalid_skipped
    )

    start_marker = _resolve_start_marker(duty, route_rows)
    end_marker = _resolve_end_marker(duty, route_rows)

    distance_km = compute_route_distance_km(route_rows)
    distance_meters = round(distance_km * 1000.0, 2) if route_rows else None

    bound_coords: list[tuple[float, float]] = []
    for marker in (start_marker, end_marker):
        if marker:
            bound_coords.append((marker["latitude"], marker["longitude"]))
    for row in route_rows:
        bound_coords.append((row["latitude"], row["longitude"]))
    for m in visit_markers:
        bound_coords.append((m["latitude"], m["longitude"]))
    map_bounds = _compute_bounds(bound_coords)

    first_at = route_rows[0]["captured_at"] if route_rows else None
    last_at = route_rows[-1]["captured_at"] if route_rows else None

    live_location = None
    if include_live_location and duty.is_active:
        live = (
            EmployeeLiveLocation.objects.filter(user_id=duty.user_id)
            .only("latitude", "longitude", "accuracy", "recorded_at", "duty_session_id")
            .first()
        )
        if live:
            pair = _valid_pair(live.latitude, live.longitude)
            if pair:
                live_location = {
                    "latitude": pair[0],
                    "longitude": pair[1],
                    "accuracy": live.accuracy,
                    "captured_at": live.recorded_at.isoformat() if live.recorded_at else None,
                    "duty_session_id": live.duty_session_id,
                }

    return {
        "duty": _duty_block_from_serialize(timer_payload, duty),
        "start_marker": start_marker,
        "visit_markers": visit_markers,
        "route_points": route_rows,
        "end_marker": end_marker,
        "summary": {
            "visit_count": len(visit_markers),
            "visits_missing_coordinates": visits_missing_coords,
            "route_point_count": route_total,
            "distance_meters": distance_meters,
            "distance_km": distance_km,
            "distance_source": DISTANCE_SOURCE_HAVERSINE,
            "first_point_at": first_at,
            "last_point_at": last_at,
            "invalid_points_skipped": len(invalid_skipped),
        },
        "map_bounds": map_bounds,
        "metadata": {
            "route_source": route_source,
            "route_points_total": route_total,
            "route_points_returned": len(route_rows),
            "route_points_sampled": sampled,
            "visit_marker_policy": "one_visit_one_marker",
            "route_includes_visit_points": True,
            "live_location_in_bounds": False,
        },
        "current_live_location": live_location,
    }


def build_admin_route_compat_payload(
    *,
    duty: DutySession | None,
    emp,
    user_id: int,
    target_date,
) -> dict[str, Any]:
    """
    Legacy admin today-route / route-by-date shape, backed by day_map_service
    when a DutySession exists for the date.
    """
    from tracking.route_utils import build_route_polyline

    if duty is None:
        return {
            "date": str(target_date),
            "user_id": user_id,
            "employee_id": getattr(emp, "employee_id", None),
            "duty_session_id": None,
            "total_points": 0,
            "distance_km": 0.0,
            "polyline": [],
            "route": [],
            "stops": [],
            "duty_started_at": None,
            "duty_ended_at": None,
            "day_map": None,
            "deprecated_note": "No DutySession for date; empty compat payload.",
        }

    day_map = build_duty_day_map(duty, include_live_location=False)
    route = [
        {
            "id": p["id"],
            "user_id": user_id,
            "duty_session_id": duty.pk,
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "accuracy": p.get("accuracy"),
            "recorded_at": p.get("captured_at"),
            "point_type": p.get("point_type") or "gps",
            "visit_id": p.get("visit_id"),
            "client_point_id": p.get("client_point_id"),
        }
        for p in day_map["route_points"]
    ]
    stops = [
        {
            "type": "visit",
            "visit_id": m["visit_id"],
            "timestamp": m.get("visited_at"),
            "latitude": m["latitude"],
            "longitude": m["longitude"],
            "farmer_id": m.get("farmer_id"),
            "farmer_name": m.get("farmer_name"),
        }
        for m in day_map["visit_markers"]
    ]
    return {
        "date": str(target_date),
        "user_id": user_id,
        "employee_id": getattr(emp, "employee_id", None),
        "duty_session_id": duty.pk,
        "total_points": day_map["metadata"]["route_points_total"],
        "distance_km": day_map["summary"]["distance_km"],
        "polyline": build_route_polyline(
            [{"latitude": p["latitude"], "longitude": p["longitude"]} for p in route]
        ),
        "route": route,
        "stops": stops,
        "duty_started_at": duty.start_time.isoformat() if duty.start_time else None,
        "duty_ended_at": duty.end_time.isoformat() if duty.end_time else None,
        "day_map": day_map,
        "route_source": day_map["metadata"]["route_source"],
    }


def get_duty_for_map(
    duty_session_id: int,
    *,
    viewer: User,
) -> DutySession:
    """Authorize and return DutySession. Hidden duties → DayMapError 404."""
    from visits.access import is_privileged_user

    duty = (
        DutySession.objects.select_related("user", "workday")
        .filter(pk=duty_session_id)
        .first()
    )
    if duty is None:
        raise DayMapError("Duty session not found.", code="NOT_FOUND", status=404)

    if is_privileged_user(viewer):
        return duty
    if duty.user_id != viewer.pk:
        raise DayMapError("Duty session not found.", code="NOT_FOUND", status=404)
    return duty
