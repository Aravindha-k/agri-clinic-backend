"""
Canonical field-visit submission service.

Every production visit-creation path must call ``submit_field_visit`` /
``submit_field_visit_validated``. Views and serializers are transport only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from tracking.employee_report import attach_visit_duty_links
from tracking.models import DutySession, EmployeeRoutePoint
from utils.gps import validate_latitude_longitude
from visits.models import Visit
from visits.services.response import build_bulk_item_response, build_visit_submit_response
from visits.submitted import visit_has_submitted_details

logger = logging.getLogger(__name__)

MAX_BULK_VISITS = 100

_WRITE_POP_KEYS = (
    "age",
    "phone",
    "phone_number",
    "acreage",
    "create_farmer_if_missing",
    "problem_subcategory",
    "status",
    "employee",
    "_resolved_problem_items",
    "problem_item_ids",
)


class FieldVisitServiceError(Exception):
    def __init__(self, message: str, *, errors: dict | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


@dataclass
class FieldVisitSubmitResult:
    visit: Visit
    created: bool
    duplicate: bool
    route_point_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def as_response(self) -> dict[str, Any]:
        if self.payload:
            return self.payload
        return build_visit_submit_response(
            self.visit,
            created=self.created,
            duplicate=self.duplicate,
            route_point_id=self.route_point_id,
        )


def visit_route_client_point_id(visit: Visit) -> str:
    return f"visit:{visit.pk}"


def resolve_duty_for_visit(visit: Visit) -> DutySession | None:
    """
    Prefer active DutySession for the employee matching visit date;
    else an unambiguous historical DutySession for employee + visit_date.
    Never invent a duty. Ambiguous multi-duty days leave visit unmatched.
    """
    if not visit.employee_id:
        return None

    if visit.duty_session_id:
        duty = visit.duty_session
        if (
            duty
            and duty.user_id == visit.employee_id
            and (visit.visit_date is None or duty.date == visit.visit_date)
        ):
            return duty
        # Wrong ownership or date mismatch — clear and re-resolve.
        Visit.objects.filter(pk=visit.pk).update(duty_session_id=None)
        visit.duty_session_id = None

    active = (
        DutySession.objects.filter(user_id=visit.employee_id, is_active=True)
        .order_by("-start_time")
        .first()
    )
    if active:
        if visit.visit_date is None or active.date == visit.visit_date:
            return active

    if visit.visit_date:
        matches = list(
            DutySession.objects.filter(
                user_id=visit.employee_id, date=visit.visit_date
            ).order_by("-start_time")[:3]
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning(
                "event=visit_duty_unmatched reason=ambiguous visit_id=%s "
                "employee_id=%s visit_date=%s candidates=%s",
                visit.pk,
                visit.employee_id,
                visit.visit_date,
                [d.pk for d in matches],
            )
            return None

    logger.info(
        "event=visit_duty_unmatched reason=no_match visit_id=%s employee_id=%s "
        "visit_date=%s",
        visit.pk,
        visit.employee_id,
        visit.visit_date,
    )
    return None


def link_visit_duty_session(visit: Visit) -> DutySession | None:
    """Attach DutySession / WorkDay without creating a work clock."""
    duty = resolve_duty_for_visit(visit)
    if duty and visit.duty_session_id != duty.pk:
        Visit.objects.filter(pk=visit.pk).update(duty_session_id=duty.pk)
        visit.duty_session_id = duty.pk
    attach_visit_duty_links(visit)
    visit.refresh_from_db(fields=["duty_session_id", "workday_id"])
    # If attach_visit_duty_links set a date-matched duty and we had none, keep it.
    if visit.duty_session_id:
        linked = visit.duty_session
        if linked and linked.user_id == visit.employee_id:
            if visit.visit_date is None or linked.date == visit.visit_date:
                return linked
            # Date mismatch from attach — prefer resolve result.
            if duty and duty.date == visit.visit_date:
                Visit.objects.filter(pk=visit.pk).update(duty_session_id=duty.pk)
                visit.duty_session_id = duty.pk
                return duty
    return duty


def ensure_visit_route_point(visit: Visit) -> EmployeeRoutePoint | None:
    """
    Create exactly one VISIT route point for a submitted visit with valid GPS.

    Idempotency key: client_point_id = ``visit:<pk>`` (and visit_id + POINT_VISIT).
    Missing/invalid coordinates → no point (visit remains valid).
    No matching DutySession → no point (visit remains valid / unmatched duty).
    """
    if not visit_has_submitted_details(visit):
        return None
    if visit.latitude is None or visit.longitude is None or not visit.employee_id:
        return None

    try:
        validate_latitude_longitude(visit.latitude, visit.longitude)
    except Exception:
        return None

    existing = (
        EmployeeRoutePoint.objects.filter(
            visit_id=visit.pk,
            point_type=EmployeeRoutePoint.POINT_VISIT,
        )
        .order_by("id")
        .first()
    )
    if existing:
        return existing

    duty = link_visit_duty_session(visit)
    if duty is None:
        return None

    client_point_id = visit_route_client_point_id(visit)
    existing_by_client = (
        EmployeeRoutePoint.objects.filter(
            duty_session=duty,
            client_point_id=client_point_id,
        )
        .order_by("id")
        .first()
    )
    if existing_by_client:
        return existing_by_client

    recorded_at = timezone.now()
    if visit.visit_date and visit.visit_time:
        recorded_at = timezone.make_aware(
            datetime.combine(visit.visit_date, visit.visit_time)
        )

    lat = Decimal(str(visit.latitude)).quantize(Decimal("0.000001"))
    lng = Decimal(str(visit.longitude)).quantize(Decimal("0.000001"))

    try:
        with transaction.atomic():
            point = EmployeeRoutePoint.objects.create(
                user=visit.employee,
                duty_session=duty,
                latitude=lat,
                longitude=lng,
                recorded_at=recorded_at,
                point_type=EmployeeRoutePoint.POINT_VISIT,
                visit_id=visit.pk,
                farmer_id=visit.farmer_id,
                is_permanent=True,
                client_point_id=client_point_id,
            )
        return point
    except IntegrityError:
        return (
            EmployeeRoutePoint.objects.filter(
                duty_session=duty, client_point_id=client_point_id
            ).first()
            or EmployeeRoutePoint.objects.filter(
                visit_id=visit.pk, point_type=EmployeeRoutePoint.POINT_VISIT
            ).first()
        )


def ensure_visit_farmer_activity(visit: Visit) -> None:
    """Deterministic FarmerActivity VISIT_COMPLETED for submitted visits."""
    if not visit_has_submitted_details(visit):
        return
    farmer = visit.farmer
    if not farmer and visit.farmer_phone:
        from masters.models import Farmer

        farmer = (
            Farmer.objects.filter(phone=visit.farmer_phone).order_by("id").first()
        )
    if not farmer:
        return

    from masters.models import FarmerActivity

    label = visit.farmer_name or farmer.name
    FarmerActivity.objects.get_or_create(
        farmer=farmer,
        activity_type="VISIT_COMPLETED",
        reference_id=visit.pk,
        defaults={
            "created_by": visit.employee,
            "notes": visit.notes or f"Field visit recorded for {label}",
        },
    )


def sync_farmer_master_idempotent(visit: Visit) -> None:
    """Idempotent farmer/field alignment without name-only matching."""
    from visits.farmer_sync import sync_visit_farmer_master

    sync_visit_farmer_master(visit)


def _resolve_employee(request, fallback: User | None) -> User:
    user = fallback or getattr(request, "user", None)
    if user is None:
        raise FieldVisitServiceError("Authenticated employee required.")
    if user.is_staff and request is not None:
        emp_id = request.data.get("employee_id") or request.data.get("employee")
        if emp_id not in (None, ""):
            try:
                return User.objects.get(pk=emp_id, is_active=True)
            except User.DoesNotExist as exc:
                raise FieldVisitServiceError(
                    "Invalid employee.",
                    errors={"employee_id": "Invalid employee."},
                ) from exc
    return user


def _clean_validated_for_create(validated_data: dict[str, Any]) -> dict[str, Any]:
    data = dict(validated_data)
    for key in _WRITE_POP_KEYS:
        data.pop(key, None)
    sync_id = (data.get("local_sync_id") or "").strip() or None
    if sync_id:
        data["local_sync_id"] = sync_id
    else:
        data.pop("local_sync_id", None)
    return data


def submit_field_visit_validated(
    *,
    employee: User,
    validated_data: dict[str, Any],
    request=None,
) -> FieldVisitSubmitResult:
    """
    Create or replay a visit from already-validated serializer data.

    Concurrency-safe on (employee, local_sync_id).
    """
    data = _clean_validated_for_create(validated_data)
    now = timezone.now()
    data.setdefault("visit_date", now.date())
    data.setdefault("visit_time", now.time())

    sync_id = data.get("local_sync_id")
    if sync_id:
        existing = Visit.objects.filter(
            employee=employee, local_sync_id=sync_id
        ).first()
        if existing:
            return _finalize_existing(existing, duplicate=True)

    try:
        with transaction.atomic():
            visit = Visit.objects.create(**data, employee=employee)
            _run_create_side_effects(visit)
            visit.refresh_from_db()
            route = ensure_visit_route_point(visit)
            return FieldVisitSubmitResult(
                visit=visit,
                created=True,
                duplicate=False,
                route_point_id=route.pk if route else None,
                payload=build_visit_submit_response(
                    visit,
                    created=True,
                    duplicate=False,
                    route_point_id=route.pk if route else None,
                ),
            )
    except IntegrityError:
        if not sync_id:
            raise
        existing = Visit.objects.filter(
            employee=employee, local_sync_id=sync_id
        ).first()
        if existing:
            return _finalize_existing(existing, duplicate=True)
        raise


def _finalize_existing(visit: Visit, *, duplicate: bool) -> FieldVisitSubmitResult:
    """Replay path: ensure side effects exist exactly once, return duplicate."""
    _run_create_side_effects(visit)
    visit.refresh_from_db()
    route = ensure_visit_route_point(visit)
    return FieldVisitSubmitResult(
        visit=visit,
        created=False,
        duplicate=duplicate,
        route_point_id=route.pk if route else None,
        payload=build_visit_submit_response(
            visit,
            created=False,
            duplicate=duplicate,
            route_point_id=route.pk if route else None,
        ),
    )


def _run_create_side_effects(visit: Visit) -> None:
    link_visit_duty_session(visit)
    sync_farmer_master_idempotent(visit)
    ensure_visit_farmer_activity(visit)


def submit_field_visit(
    *,
    employee: User,
    raw_data: dict[str, Any],
    request=None,
) -> FieldVisitSubmitResult:
    """
    Validate raw payload with FieldVisitSubmitSerializer then create/replay.
    Preferred entry for adapters that do not already hold a serializer.
    """
    from visits.field_visit_serializers import FieldVisitSubmitSerializer

    serializer = FieldVisitSubmitSerializer(
        data=raw_data, context={"request": request}
    )
    if not serializer.is_valid():
        raise serializers.ValidationError(serializer.errors)
    return submit_field_visit_validated(
        employee=employee,
        validated_data=serializer.validated_data,
        request=request,
    )


def bulk_submit_field_visits(
    *,
    employee: User,
    visits_data: list[dict[str, Any]],
    request=None,
    max_batch: int = MAX_BULK_VISITS,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Partial-success bulk submit. One savepoint per item. Preserves order.

    Returns (results, all_ok).
    """
    if not isinstance(visits_data, list):
        raise FieldVisitServiceError(
            "visits must be a list.",
            errors={"visits": "Expected a list of visit objects."},
        )
    if len(visits_data) > max_batch:
        raise FieldVisitServiceError(
            f"Batch size exceeds maximum of {max_batch}.",
            errors={"visits": f"Maximum {max_batch} visits per request."},
        )

    results: list[dict[str, Any]] = []
    all_ok = True
    for item in visits_data:
        raw = item if isinstance(item, dict) else {}
        sync_id = (raw.get("local_sync_id") or "").strip() or None
        try:
            with transaction.atomic():
                result = submit_field_visit(
                    employee=employee,
                    raw_data=raw,
                    request=request,
                )
                results.append(
                    build_bulk_item_response(
                        local_sync_id=sync_id or result.visit.local_sync_id,
                        visit=result.visit,
                        created=result.created,
                        duplicate=result.duplicate,
                        status_label="duplicate" if result.duplicate else "created",
                        errors=None,
                    )
                )
        except serializers.ValidationError as exc:
            all_ok = False
            results.append(
                build_bulk_item_response(
                    local_sync_id=sync_id,
                    visit=None,
                    created=False,
                    duplicate=False,
                    status_label="error",
                    errors=exc.detail if hasattr(exc, "detail") else str(exc),
                )
            )
        except FieldVisitServiceError as exc:
            all_ok = False
            results.append(
                build_bulk_item_response(
                    local_sync_id=sync_id,
                    visit=None,
                    created=False,
                    duplicate=False,
                    status_label="error",
                    errors=exc.errors or {"non_field_errors": [exc.message]},
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bulk visit item failed")
            all_ok = False
            results.append(
                build_bulk_item_response(
                    local_sync_id=sync_id,
                    visit=None,
                    created=False,
                    duplicate=False,
                    status_label="error",
                    errors={"non_field_errors": [str(exc)]},
                )
            )
    return results, all_ok
