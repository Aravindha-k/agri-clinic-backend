"""Admin employee day report: route, visits, duty, live location."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import EmployeeProfile
from tracking.daily_summary import (
    _visit_timestamp,
    build_visit_stops,
    compute_idle_minutes,
    compute_work_hours_seconds,
)
from tracking.duty_service import get_route_points_for_date, serialize_route_point_model
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
    """Link visit to duty session / workday for the visit date (offline-safe)."""
    if not visit.employee_id or not visit.visit_date:
        return
    updates = {}
    if not visit.duty_session_id:
        duty = (
            DutySession.objects.filter(
                user_id=visit.employee_id, date=visit.visit_date
            )
            .order_by("-start_time")
            .first()
        )
        if duty:
            updates["duty_session_id"] = duty.pk
    if not visit.workday_id:
        workday = (
            WorkDay.objects.filter(user_id=visit.employee_id, date=visit.visit_date)
            .order_by("-start_time")
            .first()
        )
        if workday:
            updates["workday_id"] = workday.pk
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


def _live_location_block(user_id: int) -> dict | None:
    live = (
        EmployeeLiveLocation.objects.filter(user_id=user_id)
        .select_related("duty_session")
        .first()
    )
    if not live:
        return None
    return {
        "latitude": float(live.latitude),
        "longitude": float(live.longitude),
        "accuracy": live.accuracy,
        "speed": live.speed,
        "battery_level": live.battery_level,
        "recorded_at": live.recorded_at.isoformat() if live.recorded_at else None,
        "duty_session_id": live.duty_session_id,
    }


def _location_endpoints(
    *,
    duty: DutySession | None,
    route: list[dict],
    live: dict | None,
) -> dict:
    start = None
    if duty and duty.latitude is not None and duty.longitude is not None:
        start = {
            "latitude": float(duty.latitude),
            "longitude": float(duty.longitude),
            "source": "duty_start",
        }
    elif route:
        start = {
            "latitude": route[0]["latitude"],
            "longitude": route[0]["longitude"],
            "source": "route_first_point",
            "recorded_at": route[0].get("recorded_at"),
        }

    latest = live
    if not latest and route:
        last = route[-1]
        latest = {
            "latitude": last["latitude"],
            "longitude": last["longitude"],
            "recorded_at": last.get("recorded_at"),
            "source": "route_last_point",
        }

    end = None
    if duty and duty.end_time and route:
        end = latest
    elif duty and not duty.is_active and latest:
        end = latest

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

    return {
        "date": str(target_date),
        "employee": _employee_block(emp, request),
        "user_id": user_id,
        "employee_id": emp.employee_id,
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
    live = _live_location_block(user_id)
    visits_payload = build_employee_visits_for_date(
        user_id=user_id, target_date=target_date, request=request
    )
    stops = build_visit_stops(user_id, target_date)
    locations = _location_endpoints(duty=duty, route=route, live=live)

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
