"""Compatibility wrappers: legacy work/workday/WorkLog APIs → DutySession."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from tracking.duty_service import (
    DutyTrackingError,
    end_duty,
    get_active_duty,
    serialize_duty_status,
    start_duty,
)
from tracking.models import DutySession
from tracking.workday_utils import WORKDAY_EXPIRED_MESSAGE, expire_overlong_workdays_for_user
from utils.response import error_response, success_response

logger = logging.getLogger(__name__)


def log_deprecated_endpoint(
    *,
    request,
    endpoint: str,
) -> None:
    user = getattr(request, "user", None)
    session_id = request.headers.get("X-Device-Session") or request.META.get(
        "HTTP_X_DEVICE_SESSION"
    )
    app_version = None
    if hasattr(request, "data") and request.data:
        app_version = request.data.get("app_version") or request.data.get("appVersion")
    logger.warning(
        "deprecated_endpoint=true endpoint=%s user_id=%s device_session_id=%s app_version=%s",
        endpoint,
        getattr(user, "pk", None),
        session_id,
        app_version,
    )


def _parse_coords(data) -> tuple[float | None, float | None]:
    lat = data.get("latitude") if data is not None else None
    lng = data.get("longitude") if data is not None else None
    latitude = float(lat) if lat not in (None, "") else None
    longitude = float(lng) if lng not in (None, "") else None
    return latitude, longitude


def legacy_start_via_duty(request, *, endpoint: str, response_style: str = "workday"):
    """
    response_style:
      - workday: StartWorkDayAPI shape {message, workday_id}
      - mobile: success_response message Workday started
      - worklog: success_response with WorkLog-like dict
    """
    log_deprecated_endpoint(request=request, endpoint=endpoint)
    if request.user.is_staff:
        return Response({"detail": "Admins cannot start workday"}, status=403)

    try:
        latitude, longitude = _parse_coords(request.data)
        result = start_duty(
            request.user, latitude=latitude, longitude=longitude
        )
    except DutyTrackingError as exc:
        code = 403 if exc.code == "FORBIDDEN" else 400
        if response_style == "workday":
            return Response({"detail": exc.message}, status=code)
        return error_response(message=exc.message, code=exc.code, status_code=code)
    except (TypeError, ValueError):
        msg = "Invalid latitude or longitude."
        if response_style == "workday":
            return Response({"detail": msg}, status=400)
        return error_response(message=msg, code="INVALID_COORDS", status_code=400)

    duty = result.duty
    payload = serialize_duty_status(request.user, duty)

    if response_style == "workday":
        return Response(
            {
                "message": "Workday started" if result.created else "Workday already started",
                "workday_id": duty.workday_id or duty.id,
                "duty_session_id": duty.id,
                "started_at": payload.get("started_at"),
                "start_time": payload.get("start_time"),
                "server_time": payload.get("server_time"),
                "is_active": True,
            },
            status=201 if result.created else 200,
        )

    if response_style == "worklog":
        return success_response(
            data=_duty_as_worklog_dict(duty),
            message="Work session started" if result.created else "Work session already active",
            status_code=200,
        )

    # mobile
    return success_response(
        data={
            "work_status": "started",
            "workday_id": duty.workday_id,
            "duty_session_id": duty.id,
            "started_at": payload.get("started_at"),
            "start_time": payload.get("start_time"),
            "server_time": payload.get("server_time"),
        },
        message="Workday started" if result.created else "Workday already started",
    )


def legacy_end_via_duty(request, *, endpoint: str, response_style: str = "workday"):
    log_deprecated_endpoint(request=request, endpoint=endpoint)
    if request.user.is_staff and response_style == "workday":
        return Response({"detail": "Admins cannot end workday"}, status=403)

    try:
        duty = end_duty(
            request.user,
            expected_duty_session_id=(
                request.data.get("duty_session_id")
                or request.data.get("expected_duty_session_id")
            ),
        )
    except DutyTrackingError as exc:
        code = 403 if exc.code == "FORBIDDEN" else 400
        if response_style == "workday":
            detail = "No active workday" if exc.code in {"NO_ACTIVE_DUTY", "NOT_FOUND"} else exc.message
            return Response({"detail": detail}, status=code)
        return error_response(message=exc.message, code=exc.code, status_code=code)

    payload = serialize_duty_status(request.user, duty)

    if response_style == "workday":
        return Response(
            {
                "message": "Workday ended",
                "ended_count": 1,
                "workday_id": duty.workday_id,
                "duty_session_id": duty.id,
                "end_time": payload.get("end_time"),
                "server_time": payload.get("server_time"),
            },
            status=200,
        )

    if response_style == "worklog":
        return success_response(
            data=_duty_as_worklog_dict(duty),
            message="Work session ended",
        )

    return success_response(
        data={
            "work_status": "not_started",
            "workday_id": duty.workday_id,
            "duty_session_id": duty.id,
            "end_time": payload.get("end_time"),
            "server_time": payload.get("server_time"),
        },
        message="Workday stopped",
    )


def mobile_work_status_payload(user: User) -> dict[str, Any]:
    expire_overlong_workdays_for_user(user)
    duty = get_active_duty(user)
    if duty and duty.is_active:
        return {
            "work_status": "started",
            "workday_id": duty.workday_id,
            "duty_session_id": duty.id,
            "started_at": duty.start_time.isoformat() if duty.start_time else None,
            "start_time": duty.start_time.isoformat() if duty.start_time else None,
            "server_time": timezone.now().isoformat(),
        }
    auto = (
        DutySession.objects.filter(user=user, auto_ended=True)
        .order_by("-end_time", "-start_time")
        .first()
    )
    if auto:
        return {
            "work_status": "expired",
            "message": WORKDAY_EXPIRED_MESSAGE,
            "code": "workday_expired",
            "workday_id": auto.workday_id,
            "duty_session_id": auto.id,
            "server_time": timezone.now().isoformat(),
        }
    return {
        "work_status": "not_started",
        "server_time": timezone.now().isoformat(),
    }


def _duty_as_worklog_dict(duty: DutySession) -> dict[str, Any]:
    duration = None
    if duty.start_time and duty.end_time:
        duration = str(duty.end_time - duty.start_time)
    return {
        "id": duty.id,
        "employee": duty.user_id,
        "start_time": duty.start_time,
        "end_time": duty.end_time,
        "total_duration": duration,
        "is_active": duty.is_active,
        "duty_session_id": duty.id,
        "workday_id": duty.workday_id,
    }


def worklog_status_payload(user: User) -> dict[str, Any] | None:
    expire_overlong_workdays_for_user(user)
    duty = get_active_duty(user)
    if not duty:
        return None
    return _duty_as_worklog_dict(duty)


def is_on_duty(user: User) -> bool:
    expire_overlong_workdays_for_user(user)
    duty = get_active_duty(user)
    return bool(duty and duty.is_active)
