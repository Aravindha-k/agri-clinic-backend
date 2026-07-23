"""Admin employee day report: route, visits, duty, live location."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import EmployeeProfile
from accounts.device_sessions import device_status_payload
from tracking.daily_summary import (
    _visit_timestamp,
    build_visit_stops,
    compute_idle_minutes,
    compute_work_hours_seconds,
)
from tracking.duty_service import get_route_points_for_date, serialize_route_point_model
from tracking.employee_status import build_status_for_live_employee
from tracking.models import DutySession, EmployeeLiveLocation, EmployeeRoutePoint, WorkDay
from tracking.route_utils import build_route_polyline, compute_route_distance_km
from utils.photo_urls import build_profile_photo_url
from visits.field_notes import resolved_recommendation, stored_observation
from visits.models import Visit
from visits.submitted import incomplete_visits_qs, submitted_visits_qs


class EmployeeNotFoundError(Exception):
    pass


def resolve_employee_profile(employee_ref: int) -> EmployeeProfile:
    """Resolve EmployeeProfile by profile pk or Django user pk."""
    emp = (
        EmployeeProfile.objects.filter(pk=employee_ref, is_active_employee=True)
        .select_related("user", "village", "village__district")
        .first()
    )
    if emp:
        return emp
    emp = (
        EmployeeProfile.objects.filter(user_id=employee_ref, is_active_employee=True)
        .select_related("user", "village", "village__district")
        .first()
    )
    if emp:
        return emp
    raise EmployeeNotFoundError(f"Employee not found: {employee_ref}")


def attach_visit_duty_links(visit: Visit) -> None:
    """
    Link visit to duty session / workday for the visit date (offline-safe).

    Only attaches when the match is deterministic (active same-date, or exactly
    one historical DutySession). Never guesses among multiple duties.
    """
    if not visit.employee_id or not visit.visit_date:
        return
    updates = {}
    if not visit.duty_session_id:
        active = (
            DutySession.objects.filter(
                user_id=visit.employee_id,
                is_active=True,
                date=visit.visit_date,
            )
            .order_by("-start_time")
            .first()
        )
        if active:
            updates["duty_session_id"] = active.pk
        else:
            matches = list(
                DutySession.objects.filter(
                    user_id=visit.employee_id, date=visit.visit_date
                ).order_by("-start_time")[:3]
            )
            if len(matches) == 1:
                updates["duty_session_id"] = matches[0].pk

    if not visit.workday_id:
        workdays = list(
            WorkDay.objects.filter(
                user_id=visit.employee_id, date=visit.visit_date
            ).order_by("-start_time")[:3]
        )
        if len(workdays) == 1:
            updates["workday_id"] = workdays[0].pk
        elif len(workdays) > 1:
            # Prefer workday linked to the chosen/known duty when available.
            duty_id = updates.get("duty_session_id") or visit.duty_session_id
            if duty_id:
                linked = (
                    WorkDay.objects.filter(
                        user_id=visit.employee_id,
                        date=visit.visit_date,
                        duty_session__pk=duty_id,
                    )
                    .order_by("-start_time")
                    .first()
                )
                if linked:
                    updates["workday_id"] = linked.pk
    if updates:
        Visit.objects.filter(pk=visit.pk).update(**updates)


def _build_route_for_date(user_id: int, target_date: date) -> tuple[list[dict], str, float]:
    points = get_route_points_for_date(user_id, target_date)
    route = [serialize_route_point_model(p) for p in points]
    polyline = build_route_polyline(route)
    distance_km = compute_route_distance_km(route)
    return route, polyline, distance_km


def _serialize_crop_fields(visit: Visit) -> dict:
    """Crop FK + display labels for admin day report visit rows."""
    from visits.visit_response import crop_display_name

    crop_name = crop_display_name(visit) or None
    crop_variety = (visit.variety or "").strip() or None
    crop_stage = (visit.crop_stage or "").strip() or None

    return {
        "crop_id": visit.crop_id,
        "crop_name": crop_name,
        "crop_variety": crop_variety,
        "crop_stage": crop_stage,
    }


def _serialize_visit_row(visit: Visit, request) -> dict:
    farmer_name = visit.farmer_name
    if not farmer_name and visit.farmer_id:
        farmer_name = visit.farmer.name
    village_name = visit.village.name if visit.village_id else None
    ts = _visit_timestamp(visit)
    remarks_parts = [
        stored_observation(visit),
        resolved_recommendation(visit),
        visit.field_notes,
        visit.notes,
        visit.action_taken,
    ]
    remarks = "\n".join(p.strip() for p in remarks_parts if p and str(p).strip()) or None

    photos = []
    for att in visit.attachments.all():
        url = None
        if att.file:
            try:
                url = request.build_absolute_uri(att.file.url) if request else att.file.url
            except (ValueError, AttributeError):
                url = None
        photos.append(
            {
                "id": att.id,
                "type": att.attachment_type,
                "url": url,
                "caption": att.text_content or att.original_filename or "",
            }
        )
    for media in visit.media_files.all():
        url = None
        if media.file:
            try:
                url = request.build_absolute_uri(media.file.url) if request else media.file.url
            except (ValueError, AttributeError):
                url = None
        photos.append(
            {
                "id": media.id,
                "type": media.media_type,
                "url": url,
                "caption": media.caption or "",
            }
        )

    is_submitted = submitted_visits_qs(Visit.objects.filter(pk=visit.pk)).exists()

    return {
        "visit_id": visit.id,
        "farmer_id": visit.farmer_id,
        "farmer_name": farmer_name,
        "village_id": visit.village_id,
        "village_name": village_name,
        **_serialize_crop_fields(visit),
        "latitude": float(visit.latitude) if visit.latitude is not None else None,
        "longitude": float(visit.longitude) if visit.longitude is not None else None,
        "visit_date": str(visit.visit_date) if visit.visit_date else None,
        "visit_time": visit.visit_time.isoformat() if visit.visit_time else None,
        "timestamp": ts.isoformat() if ts else None,
        "status": visit.status,
        "is_submitted": is_submitted,
        "is_offline_sync": bool((visit.local_sync_id or "").strip()),
        "local_sync_id": visit.local_sync_id,
        "duty_session_id": visit.duty_session_id,
        "workday_id": visit.workday_id,
        "remarks": remarks,
        "observation": stored_observation(visit) or None,
        "recommendation": resolved_recommendation(visit) or None,
        "field_notes": visit.field_notes,
        "photos": photos,
        "photo_count": len(photos),
        "follow_up_required": visit.follow_up_required,
        "next_visit_date": str(visit.next_visit_date) if visit.next_visit_date else None,
    }


def build_employee_visits_for_date(
    *,
    user_id: int,
    target_date: date,
    request,
) -> dict:
    base_qs = (
        Visit.objects.filter(employee_id=user_id, visit_date=target_date)
        .select_related("farmer", "village", "crop", "duty_session", "workday")
        .prefetch_related("attachments", "media_files")
        .order_by("visit_time", "created_at", "id")
    )
    submitted = list(submitted_visits_qs(base_qs))
    submitted_ids = {v.id for v in submitted}
    pending_qs = incomplete_visits_qs().filter(
        employee_id=user_id, visit_date=target_date
    ).select_related("farmer", "village", "crop").prefetch_related(
        "attachments", "media_files"
    ).order_by("visit_time", "created_at", "id")
    pending = list(pending_qs)

    visit_list = [_serialize_visit_row(v, request) for v in base_qs]

    return {
        "date": str(target_date),
        "user_id": user_id,
        "total_visits": base_qs.count(),
        "completed_visits": len(submitted),
        "pending_visits": len(pending),
        "visits": visit_list,
        "completed": [_serialize_visit_row(v, request) for v in submitted],
        "pending": [_serialize_visit_row(v, request) for v in pending],
    }


def _employee_block(emp: EmployeeProfile, request) -> dict:
    return {
        "profile_id": emp.pk,
        "user_id": emp.user_id,
        "employee_id": emp.employee_id,
        "username": emp.user.username,
        "phone": emp.phone or "",
        "profile_photo_url": build_profile_photo_url(request, emp.profile_photo),
        "district": (
            emp.village.district.name if emp.village and emp.village.district else None
        ),
        "village": emp.village.name if emp.village else None,
    }


def _duty_block(duty: DutySession | None) -> dict:
    if not duty:
        return {
            "duty_session_id": None,
            "workday_id": None,
            "started_at": None,
            "ended_at": None,
            "is_active": False,
            "status": "NO_DUTY",
            "auto_ended": False,
        }
    status = "ACTIVE" if duty.is_active else ("AUTO_ENDED" if duty.auto_ended else "ENDED")
    return {
        "duty_session_id": duty.id,
        "workday_id": duty.workday_id,
        "started_at": duty.start_time.isoformat() if duty.start_time else None,
        "ended_at": duty.end_time.isoformat() if duty.end_time else None,
        "is_active": duty.is_active,
        "status": status,
        "auto_ended": duty.auto_ended,
        "start_latitude": float(duty.latitude) if duty.latitude is not None else None,
        "start_longitude": float(duty.longitude) if duty.longitude is not None else None,
    }


def _live_location_model(user_id: int) -> EmployeeLiveLocation | None:
    return (
        EmployeeLiveLocation.objects.filter(user_id=user_id)
        .select_related("duty_session")
        .first()
    )


def _live_location_block_from_model(live: EmployeeLiveLocation | None) -> dict | None:
    if not live:
        return None
    return {
        "latitude": float(live.latitude) if live.latitude is not None else None,
        "longitude": float(live.longitude) if live.longitude is not None else None,
        "accuracy": live.accuracy,
        "speed": live.speed,
        "battery_level": live.battery_level,
        "recorded_at": live.recorded_at.isoformat() if live.recorded_at else None,
        "duty_session_id": live.duty_session_id,
        "last_heartbeat_at": (
            live.last_heartbeat_at.isoformat() if live.last_heartbeat_at else None
        ),
    }


def _employee_status_block(*, user: User, duty: DutySession | None, live, now) -> dict:
    from tracking.employee_status import batch_gps_off_user_ids
    from tracking.models import EmployeeGpsState

    gps_state = EmployeeGpsState.objects.filter(user=user).first()
    gps_off = user.pk in batch_gps_off_user_ids([user.pk])
    return build_status_for_live_employee(
        user_id=user.pk,
        live_row=live,
        gps_state_row=gps_state,
        has_active_duty=bool(duty and duty.is_active),
        device_status=device_status_payload(user),
        gps_off=gps_off,
        last_heartbeat_at=duty.last_heartbeat if duty else None,
        now=now,
    )


def _location_endpoints(
    *,
    duty: DutySession | None,
    route: list[dict],
    live: dict | None,
) -> dict:
    """
    Start/end endpoints for admin day report.

    Start is only DutySession start coords — never first GPS heartbeat or visit.
    """
    start = None
    if duty and duty.latitude is not None and duty.longitude is not None:
        start = {
            "latitude": float(duty.latitude),
            "longitude": float(duty.longitude),
            "source": "duty_start",
            "captured_at": duty.start_time.isoformat() if duty.start_time else None,
        }

    latest = live

    end = None
    if duty and not duty.is_active:
        end_point = (
            EmployeeRoutePoint.objects.filter(
                duty_session_id=duty.pk,
                point_type=EmployeeRoutePoint.POINT_END,
            )
            .order_by("id")
            .first()
        )
        if end_point is not None:
            end = {
                "latitude": float(end_point.latitude),
                "longitude": float(end_point.longitude),
                "source": "duty_end",
                "recorded_at": (
                    end_point.recorded_at.isoformat() if end_point.recorded_at else None
                ),
            }

    return {"start": start, "latest": latest, "end": end}


def build_employee_day_summary(
    *,
    emp: EmployeeProfile,
    target_date: date,
    request=None,
    now=None,
) -> dict:
    """Day summary using duty route points + visit counts."""
    user_id = emp.user_id
    route, _polyline, distance_km = _build_route_for_date(user_id, target_date)
    idle_minutes = compute_idle_minutes(route)

    workdays = list(
        WorkDay.objects.filter(user_id=user_id, date=target_date).order_by("start_time")
    )
    work_seconds = compute_work_hours_seconds(workdays, target_date, now=now)
    hours, remainder = divmod(max(work_seconds, 0), 3600)
    work_hours = f"{hours}h {remainder // 60}m"

    visits_qs = submitted_visits_qs().filter(employee_id=user_id, visit_date=target_date)
    visits_completed = visits_qs.count()
    pending_visits = incomplete_visits_qs().filter(
        employee_id=user_id, visit_date=target_date
    ).count()

    duty = (
        DutySession.objects.filter(user_id=user_id, date=target_date)
        .order_by("-start_time")
        .first()
    )
    live_model = _live_location_model(user_id)
    status = _employee_status_block(
        user=emp.user,
        duty=duty,
        live=live_model,
        now=now or timezone.now(),
    )

    return {
        "date": str(target_date),
        "employee": _employee_block(emp, request),
        "user_id": user_id,
        "employee_id": emp.employee_id,
        **status,
        "status": status,
        "duty": _duty_block(duty),
        "work_hours_seconds": work_seconds,
        "work_hours": work_hours,
        "distance_km": distance_km,
        "route_point_count": len(route),
        "visits_completed": visits_completed,
        "pending_visits": pending_visits,
        "farmers_covered": visits_qs.filter(farmer_id__isnull=False)
        .values("farmer_id")
        .distinct()
        .count(),
        "villages_covered": visits_qs.filter(village_id__isnull=False)
        .values("village_id")
        .distinct()
        .count(),
        "idle_minutes": idle_minutes,
        "workday_count": len(workdays),
    }


def build_employee_day_report(
    *,
    emp: EmployeeProfile,
    target_date: date,
    request,
    now=None,
) -> dict:
    """Full admin day report for one employee."""
    now = now or timezone.now()
    user_id = emp.user_id

    duty = (
        DutySession.objects.filter(user_id=user_id, date=target_date)
        .order_by("-start_time")
        .first()
    )
    route, polyline, distance_km = _build_route_for_date(user_id, target_date)
    live_model = _live_location_model(user_id)
    live = _live_location_block_from_model(live_model)
    status = _employee_status_block(
        user=emp.user,
        duty=duty,
        live=live_model,
        now=now,
    )
    visits_payload = build_employee_visits_for_date(
        user_id=user_id, target_date=target_date, request=request
    )
    stops = build_visit_stops(user_id, target_date)
    locations = _location_endpoints(duty=duty, route=route, live=live)

    day_map = None
    if duty is not None:
        from tracking.day_map_service import build_duty_day_map

        day_map = build_duty_day_map(duty, include_live_location=False)

    offline_visit_count = sum(1 for v in visits_payload["visits"] if v.get("is_offline_sync"))
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    day_end = day_start + timedelta(days=1)
    permanent_stops = EmployeeRoutePoint.objects.filter(
        user_id=user_id,
        recorded_at__gte=day_start,
        recorded_at__lt=day_end,
        is_permanent=True,
    ).count()

    summary = build_employee_day_summary(
        emp=emp, target_date=target_date, request=request, now=now
    )

    return {
        "date": str(target_date),
        "employee": _employee_block(emp, request),
        **status,
        "status": status,
        "duty": _duty_block(duty),
        "live_location": live,
        "route": {
            "polyline": polyline,
            "point_count": len(route),
            "distance_km": distance_km,
            "points": route,
            "stops": stops,
        },
        "locations": locations,
        "day_map": day_map,
        "start_marker": None if day_map is None else day_map.get("start_marker"),
        "visit_markers": [] if day_map is None else day_map.get("visit_markers") or [],
        "end_marker": None if day_map is None else day_map.get("end_marker"),
        "markers": {
            "start": None if day_map is None else day_map.get("start_marker"),
            "visits": [] if day_map is None else day_map.get("visit_markers") or [],
            "end": None if day_map is None else day_map.get("end_marker"),
        },
        "visits": visits_payload,
        "summary": {
            "work_hours": summary["work_hours"],
            "work_hours_seconds": summary["work_hours_seconds"],
            "distance_km": distance_km,
            "route_point_count": len(route),
            "total_visits": visits_payload["total_visits"],
            "completed_visits": visits_payload["completed_visits"],
            "pending_visits": visits_payload["pending_visits"],
            "idle_minutes": summary["idle_minutes"],
            "farmers_covered": summary["farmers_covered"],
            "villages_covered": summary["villages_covered"],
        },
        "offline_sync": {
            "visits_synced_offline": offline_visit_count,
            "permanent_route_stops": permanent_stops,
        },
    }
