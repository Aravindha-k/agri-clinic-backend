"""Atomic check-in / check-out business logic and summary roll-ups."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from attendance.models import (
    AttendanceAuditLog,
    AttendanceDailySummary,
    AttendanceDevice,
    AttendanceEmployee,
    AttendanceEvent,
    EmployeeShopAssignment,
    Shift,
    Shop,
)

logger = logging.getLogger(__name__)

HALF_DAY_THRESHOLD_SECONDS = 4 * 3600
# Sessions open longer than this are treated as abandoned (missing checkout).
MAX_OPEN_SESSION_HOURS = 20


class AttendanceError(Exception):
    def __init__(self, message: str, code: str = "ATTENDANCE_ERROR"):
        super().__init__(message)
        self.code = code


class EmployeeInactive(AttendanceError):
    def __init__(self):
        super().__init__(
            "Employee is deactivated and cannot record attendance.",
            code="EMPLOYEE_INACTIVE",
        )


class NotAssigned(AttendanceError):
    def __init__(self):
        super().__init__(
            "Employee is not assigned to this shop.", code="NOT_ASSIGNED"
        )


class OpenSessionExists(AttendanceError):
    def __init__(self):
        super().__init__(
            "Employee already has an open check-in at this shop.",
            code="OPEN_SESSION_EXISTS",
        )


class NoOpenSession(AttendanceError):
    def __init__(self):
        super().__init__(
            "No open check-in found for this employee at this shop.",
            code="NO_OPEN_SESSION",
        )


@dataclass
class EventResult:
    event: AttendanceEvent
    idempotent_replay: bool = False


def _local_date(dt: datetime):
    return timezone.localtime(dt).date()


def find_shift_for(shop: Shop, at: datetime) -> Shift | None:
    """Return the shop (or global) shift whose window contains `at`.

    Overnight shifts (end <= start) match when local time is >= start or
    < end. Shop-specific shifts win over global fallbacks; earliest start wins.
    """
    local_t = timezone.localtime(at).time()
    candidates = (
        Shift.objects.filter(is_active=True)
        .filter(Q(shop=shop) | Q(shop__isnull=True))
        .order_by("start_time")
    )
    for shift in candidates:
        s, e = shift.start_time, shift.end_time
        if shift.crosses_midnight:
            if local_t >= s or local_t < e:
                return shift
        elif s <= local_t < e:
            return shift
    return None


def _get_locked_assignment(employee: AttendanceEmployee, shop: Shop):
    """Lock the (employee, shop) assignment row — serializes all attendance
    writes for this pair within the transaction."""
    return (
        EmployeeShopAssignment.objects.select_for_update()
        .filter(employee=employee, shop=shop, is_active=True)
        .first()
    )


def _validate_assignment_window(assignment, today) -> None:
    if assignment.valid_from and today < assignment.valid_from:
        raise NotAssigned()
    if assignment.valid_to and today > assignment.valid_to:
        raise NotAssigned()


def _latest_event(employee: AttendanceEmployee, shop: Shop):
    return (
        AttendanceEvent.objects.filter(employee=employee, shop=shop)
        .order_by("-occurred_at", "-id")
        .first()
    )


def _replay_for_client_id(
    device: AttendanceDevice | None, client_event_id: str | None
) -> AttendanceEvent | None:
    if not device or not client_event_id:
        return None
    return AttendanceEvent.objects.filter(
        device=device, client_event_id=client_event_id
    ).first()


def _audit(*, action, device=None, actor=None, entity=None, metadata=None, request=None):
    ip = None
    if request is not None:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None
    AttendanceAuditLog.objects.create(
        actor=actor,
        device=device,
        action=action,
        entity_type=entity.__class__.__name__ if entity is not None else "",
        entity_id=str(getattr(entity, "pk", "") or ""),
        metadata=metadata or {},
        ip_address=ip,
    )


@transaction.atomic
def perform_event(
    *,
    employee: AttendanceEmployee,
    shop: Shop,
    device: AttendanceDevice | None,
    event_type: str,
    verification,
    client_event_id: str | None = None,
    latitude=None,
    longitude=None,
    recorded_by=None,
    notes: str = "",
    request=None,
) -> EventResult:
    if event_type not in {
        AttendanceEvent.EVENT_CHECK_IN,
        AttendanceEvent.EVENT_CHECK_OUT,
    }:
        raise AttendanceError("Invalid event type.", code="INVALID_EVENT_TYPE")

    existing = _replay_for_client_id(device, client_event_id)
    if existing is not None:
        if existing.event_type != event_type or existing.employee_id != employee.id:
            raise AttendanceError(
                "client_event_id was already used for a different event.",
                code="IDEMPOTENCY_CONFLICT",
            )
        return EventResult(event=existing, idempotent_replay=True)

    if not employee.is_active:
        raise EmployeeInactive()

    assignment = _get_locked_assignment(employee, shop)
    if assignment is None:
        raise NotAssigned()
    _validate_assignment_window(assignment, timezone.localdate())

    now = timezone.now()
    latest = _latest_event(employee, shop)

    if event_type == AttendanceEvent.EVENT_CHECK_IN:
        if latest is not None and latest.event_type == AttendanceEvent.EVENT_CHECK_IN:
            raise OpenSessionExists()
        shift = find_shift_for(shop, now)
    else:
        if latest is None or latest.event_type != AttendanceEvent.EVENT_CHECK_IN:
            raise NoOpenSession()
        shift = latest.shift  # inherit the shift of the paired check-in

    event = AttendanceEvent.objects.create(
        employee=employee,
        shop=shop,
        device=device,
        shift=shift,
        event_type=event_type,
        occurred_at=now,
        client_event_id=client_event_id or None,
        verification_method=verification.method,
        is_test_mode=verification.is_test_mode,
        latitude=latitude,
        longitude=longitude,
        recorded_by=recorded_by,
        notes=notes,
    )
    _audit(
        action="CHECK_IN" if event_type == AttendanceEvent.EVENT_CHECK_IN else "CHECK_OUT",
        device=device,
        actor=recorded_by,
        entity=event,
        metadata={
            "employee_code": employee.employee_code,
            "verification_method": verification.method,
            "is_test_mode": verification.is_test_mode,
        },
        request=request,
    )
    rebuild_summaries(employee=employee, shop=shop)
    return EventResult(event=event)


def _events_for_pair(employee: AttendanceEmployee, shop: Shop) -> Iterable[AttendanceEvent]:
    return AttendanceEvent.objects.filter(employee=employee, shop=shop).order_by(
        "occurred_at", "id"
    )


def rebuild_summaries(*, employee: AttendanceEmployee, shop: Shop) -> None:
    """Rebuild all AttendanceDailySummary rows for an (employee, shop) pair.

    Pairs consecutive CHECK_IN -> CHECK_OUT events. Worked time and status are
    attributed to the check-in's local date, so overnight sessions count on
    the day the employee checked in.
    """
    events = list(_events_for_pair(employee, shop))
    by_date: dict = {}
    open_in: AttendanceEvent | None = None

    def bucket(d):
        return by_date.setdefault(
            d,
            {
                "worked": 0,
                "first_in": None,
                "last_out": None,
                "open": False,
                "test": False,
            },
        )

    for ev in events:
        if ev.is_test_mode:
            # mark test presence on the event's own local date
            bucket(_local_date(ev.occurred_at))["test"] = True
        if ev.event_type == AttendanceEvent.EVENT_CHECK_IN:
            open_in = ev  # latest open in-order
            d = _local_date(ev.occurred_at)
            b = bucket(d)
            if b["first_in"] is None:
                b["first_in"] = ev.occurred_at
            b["open"] = True
        else:  # CHECK_OUT
            if open_in is not None:
                d = _local_date(open_in.occurred_at)
                b = bucket(d)
                b["worked"] += max(
                    0, int((ev.occurred_at - open_in.occurred_at).total_seconds())
                )
                b["last_out"] = ev.occurred_at
                b["open"] = False
                open_in = None
            else:
                # orphan checkout: attribute to its own date, no worked time
                bucket(_local_date(ev.occurred_at))

    # Persist: delete stale rows, upsert computed ones.
    AttendanceDailySummary.objects.filter(employee=employee, shop=shop).exclude(
        date__in=by_date.keys() or [None]
    ).delete()
    for d, b in by_date.items():
        if b["open"] and b["worked"] == 0:
            status = AttendanceDailySummary.STATUS_INCOMPLETE
        elif b["worked"] >= HALF_DAY_THRESHOLD_SECONDS:
            status = AttendanceDailySummary.STATUS_PRESENT
        elif b["worked"] > 0:
            status = AttendanceDailySummary.STATUS_HALF_DAY
        else:
            status = AttendanceDailySummary.STATUS_INCOMPLETE
        AttendanceDailySummary.objects.update_or_create(
            employee=employee,
            shop=shop,
            date=d,
            defaults={
                "first_check_in": b["first_in"],
                "last_check_out": b["last_out"],
                "worked_seconds": b["worked"],
                "status": status,
                "has_open_session": b["open"],
                "contains_test_events": b["test"],
            },
        )


def open_session(employee: AttendanceEmployee, shop: Shop) -> AttendanceEvent | None:
    latest = _latest_event(employee, shop)
    if latest is not None and latest.event_type == AttendanceEvent.EVENT_CHECK_IN:
        return latest
    return None


# --------------------------------------------------------------------------
# Admin helpers: auto codes, employee creation with assignment, transfer
# --------------------------------------------------------------------------


def _next_numeric_code(model, field: str, prefix: str, width: int = 4) -> str:
    """Next ``PREFIX-000N`` code. Race-safe only inside a retry loop on the
    unique constraint — callers must catch IntegrityError and retry."""
    startswith = f"{field}__startswith"
    existing = model.objects.filter(**{startswith: f"{prefix}-"}).values_list(
        field, flat=True
    )
    highest = 0
    for value in existing:
        suffix = str(value).rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}-{highest + 1:0{width}d}"


def create_shop(*, name: str, area: str = "", code: str | None = None,
                **fields) -> Shop:
    """Create a shop, auto-generating ``code`` when not supplied."""
    explicit = bool(code)
    for _attempt in range(10):
        candidate = code or _next_numeric_code(Shop, "code", "SHOP")
        try:
            with transaction.atomic():
                return Shop.objects.create(
                    code=candidate, name=name, area=area, **fields
                )
        except IntegrityError:
            if explicit:
                raise
    raise AttendanceError("Could not allocate a unique shop code.",
                          code="SHOP_CODE_EXHAUSTED")


def create_employee(*, full_name: str, phone: str = "", shop: Shop | None = None,
                    employee_code: str | None = None,
                    linked_profile=None, created_by=None) -> AttendanceEmployee:
    """Create an AttendanceEmployee (+ optional initial shop assignment)
    atomically. Never creates a Django user or Field Officer credentials."""
    if shop is not None and not shop.is_active:
        raise AttendanceError("Selected shop is not active.",
                              code="SHOP_INACTIVE")
    explicit = bool(employee_code)
    for _attempt in range(10):
        candidate = employee_code or _next_numeric_code(
            AttendanceEmployee, "employee_code", "EMP"
        )
        try:
            with transaction.atomic():
                emp = AttendanceEmployee.objects.create(
                    employee_code=candidate,
                    full_name=full_name,
                    phone=phone,
                    linked_profile=linked_profile,
                    created_by=created_by,
                    updated_by=created_by,
                )
                if shop is not None:
                    EmployeeShopAssignment.objects.create(
                        employee=emp, shop=shop, is_active=True,
                        created_by=created_by,
                    )
                return emp
        except IntegrityError:
            if explicit:
                raise
    raise AttendanceError("Could not allocate a unique employee code.",
                          code="EMPLOYEE_CODE_EXHAUSTED")


def transfer_employee(employee: AttendanceEmployee, to_shop: Shop,
                      actor=None) -> tuple[EmployeeShopAssignment, list[int]]:
    """Atomically end all active assignments and activate one for ``to_shop``.

    Historical assignments/events/summaries are preserved — only is_active /
    valid_to change. Returns (assignment, previous_active_shop_ids).
    """
    if not to_shop.is_active:
        raise AttendanceError("Destination shop is not active.",
                              code="SHOP_INACTIVE")
    if not employee.is_active:
        raise AttendanceError("Employee is not active.",
                              code="EMPLOYEE_INACTIVE")
    with transaction.atomic():
        active_qs = EmployeeShopAssignment.objects.select_for_update().filter(
            employee=employee, is_active=True
        )
        previous_shop_ids = list(active_qs.values_list("shop_id", flat=True))
        today = timezone.localdate()
        active_qs.update(is_active=False, valid_to=today)
        assignment, created = EmployeeShopAssignment.objects.get_or_create(
            employee=employee,
            shop=to_shop,
            defaults={"is_active": True, "created_by": actor},
        )
        if not created:
            assignment.is_active = True
            assignment.valid_to = None
            assignment.save(update_fields=["is_active", "valid_to", "updated_at"])
    return assignment, previous_shop_ids
