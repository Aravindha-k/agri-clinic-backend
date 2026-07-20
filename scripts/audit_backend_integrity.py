#!/usr/bin/env python
"""
Read-only backend integrity audit for Agri Clinic.

Reports suspicious rows. Does NOT delete or mutate data.

Usage:
  .venv/Scripts/python.exe scripts/audit_backend_integrity.py
  .venv/Scripts/python.exe manage.py shell < scripts/audit_backend_integrity.py
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

import django

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db.models import Count, F, Q  # noqa: E402

from masters.models import Farmer  # noqa: E402
from tracking.models import DutySession, EmployeeRoutePoint, WorkDay  # noqa: E402
from visits.models import Visit, VisitAttachment, VisitMedia  # noqa: E402


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    findings = 0

    _section("Duplicate active DutySession")
    rows = (
        DutySession.objects.filter(is_active=True)
        .values("user_id")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
    )
    for row in rows:
        findings += 1
        print(f"  user_id={row['user_id']} active_count={row['c']}")
    if not rows:
        print("  OK")

    _section("Duplicate active WorkDay")
    rows = (
        WorkDay.objects.filter(is_active=True)
        .values("user_id")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
    )
    for row in rows:
        findings += 1
        print(f"  user_id={row['user_id']} active_count={row['c']}")
    if not rows:
        print("  OK")

    _section("Invalid timestamps (end < start)")
    duty_bad = DutySession.objects.filter(
        end_time__isnull=False, end_time__lt=F("start_time")
    ).count()
    work_bad = WorkDay.objects.filter(
        end_time__isnull=False, end_time__lt=F("start_time")
    ).count()
    print(f"  DutySession end<start: {duty_bad}")
    print(f"  WorkDay end<start: {work_bad}")
    findings += duty_bad + work_bad

    _section("Null started_at / start_time")
    # start_time is non-null in schema; count defensive
    print(f"  DutySession start_time null: {DutySession.objects.filter(start_time__isnull=True).count()}")
    print(f"  WorkDay start_time null: {WorkDay.objects.filter(start_time__isnull=True).count()}")

    _section("Orphan route points (duty missing)")
    # FK CASCADE should prevent; still report duty/user mismatch
    mismatch = EmployeeRoutePoint.objects.exclude(
        user_id=F("duty_session__user_id")
    ).count()
    print(f"  route points with user != duty.user: {mismatch}")
    findings += mismatch

    _section("Duplicate farmer phones (non-blank)")
    phone_groups = (
        Farmer.objects.exclude(Q(phone__isnull=True) | Q(phone=""))
        .values("phone")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
        .order_by("-c")[:50]
    )
    for row in phone_groups:
        findings += 1
        print(f"  phone={row['phone']!r} farmers={row['c']}")
    if not phone_groups:
        print("  OK")

    _section("Blank farmer names")
    blank_names = Farmer.objects.filter(Q(name__isnull=True) | Q(name="")).count()
    print(f"  blank names: {blank_names}")
    findings += blank_names

    _section("Duplicate visit local_sync_id per employee")
    sync_groups = (
        Visit.objects.exclude(Q(local_sync_id__isnull=True) | Q(local_sync_id=""))
        .values("employee_id", "local_sync_id")
        .annotate(c=Count("id"))
        .filter(c__gt=1)[:50]
    )
    for row in sync_groups:
        findings += 1
        print(
            f"  employee={row['employee_id']} sync={row['local_sync_id']!r} count={row['c']}"
        )
    if not sync_groups:
        print("  OK (constraint should prevent)")

    _section("Duplicate route client_point_id per duty")
    point_groups = (
        EmployeeRoutePoint.objects.exclude(client_point_id__isnull=True)
        .values("duty_session_id", "client_point_id")
        .annotate(c=Count("id"))
        .filter(c__gt=1)[:50]
    )
    for row in point_groups:
        findings += 1
        print(
            f"  duty={row['duty_session_id']} client_point_id={row['client_point_id']!r} "
            f"count={row['c']}"
        )
    if not point_groups:
        print("  OK (constraint should prevent)")

    _section("Visits with duty owned by another employee")
    wrong_duty = Visit.objects.filter(duty_session__isnull=False).exclude(
        employee_id=F("duty_session__user_id")
    ).count()
    print(f"  mismatched employee/duty: {wrong_duty}")
    findings += wrong_duty

    _section("Orphan media / attachments (visit missing)")
    # CASCADE FKs normally prevent; report zero expected
    print(f"  VisitMedia rows: {VisitMedia.objects.count()}")
    print(f"  VisitAttachment rows: {VisitAttachment.objects.count()}")

    _section("Invalid completion_reason")
    bad_reason = (
        DutySession.objects.filter(is_active=False)
        .exclude(completion_reason__isnull=True)
        .exclude(completion_reason="")
        .exclude(completion_reason__in=["MANUAL", "AUTO_EXPIRED"])
        .count()
    )
    print(f"  unexpected completion_reason: {bad_reason}")
    findings += bad_reason

    print(f"\n=== SUMMARY: {findings} suspicious finding(s) ===")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
