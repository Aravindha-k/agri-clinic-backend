"""
Dry-run / apply repair for DutySession ↔ WorkDay ↔ WorkLog inconsistencies.

Usage:
  python manage.py repair_duty_consistency --dry-run
  python manage.py repair_duty_consistency --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tracking.models import DutySession, WorkDay
from tracking.worklog import WorkLog


class Command(BaseCommand):
    help = "Report (and optionally repair) conflicting duty/workday/worklog state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Report only (default).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply repairs. Without this flag only a dry-run report is produced.",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        dry_run = not apply
        report = {
            "active_workday_without_duty": [],
            "active_duty_inactive_workday": [],
            "active_worklog_without_duty": [],
            "repairs": [],
        }

        # 1) Active WorkDay with no active DutySession
        for wd in WorkDay.objects.filter(is_active=True).select_related("user"):
            duty = DutySession.objects.filter(user=wd.user, is_active=True).first()
            if duty is None:
                report["active_workday_without_duty"].append(
                    {
                        "user_id": wd.user_id,
                        "workday_id": wd.id,
                        "start_time": wd.start_time.isoformat() if wd.start_time else None,
                    }
                )
                if apply:
                    with transaction.atomic():
                        created = DutySession.objects.create(
                            user=wd.user,
                            workday=wd,
                            date=wd.date or timezone.localdate(),
                            start_time=wd.start_time or timezone.now(),
                            is_active=True,
                            last_heartbeat=wd.last_heartbeat or wd.start_time,
                            latitude=wd.latitude,
                            longitude=wd.longitude,
                        )
                        report["repairs"].append(
                            f"created DutySession id={created.id} for WorkDay id={wd.id}"
                        )

        # 2) Active DutySession with inactive / missing WorkDay
        for duty in DutySession.objects.filter(is_active=True).select_related(
            "workday", "user"
        ):
            wd = duty.workday
            if wd is None or not wd.is_active:
                report["active_duty_inactive_workday"].append(
                    {
                        "user_id": duty.user_id,
                        "duty_id": duty.id,
                        "workday_id": duty.workday_id,
                        "workday_active": bool(wd and wd.is_active),
                    }
                )
                if apply:
                    with transaction.atomic():
                        if wd is None:
                            wd = WorkDay.objects.create(
                                user=duty.user,
                                date=duty.date,
                                start_time=duty.start_time,
                                is_active=True,
                                last_heartbeat=duty.last_heartbeat or duty.start_time,
                                latitude=duty.latitude,
                                longitude=duty.longitude,
                            )
                            duty.workday = wd
                            duty.save(update_fields=["workday"])
                            report["repairs"].append(
                                f"created WorkDay id={wd.id} for DutySession id={duty.id}"
                            )
                        else:
                            wd.is_active = True
                            wd.end_time = None
                            wd.auto_ended = False
                            wd.save(
                                update_fields=["is_active", "end_time", "auto_ended"]
                            )
                            report["repairs"].append(
                                f"reactivated WorkDay id={wd.id} for DutySession id={duty.id}"
                            )

        # 3) Active WorkLog while no active DutySession → deactivate WorkLog (do not invent duty)
        for log in WorkLog.objects.filter(is_active=True).select_related("employee"):
            if not DutySession.objects.filter(
                user=log.employee, is_active=True
            ).exists():
                report["active_worklog_without_duty"].append(
                    {
                        "user_id": log.employee_id,
                        "worklog_id": log.id,
                        "start_time": log.start_time.isoformat()
                        if log.start_time
                        else None,
                    }
                )
                if apply:
                    now = timezone.now()
                    log.is_active = False
                    log.end_time = log.end_time or now
                    if log.start_time and log.end_time:
                        log.total_duration = log.end_time - log.start_time
                    log.save(
                        update_fields=[
                            "is_active",
                            "end_time",
                            "total_duration",
                        ]
                    )
                    report["repairs"].append(
                        f"deactivated orphan WorkLog id={log.id} user_id={log.employee_id}"
                    )

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(self.style.NOTICE(f"=== repair_duty_consistency ({mode}) ===="))
        self.stdout.write(
            f"active_workday_without_duty: {len(report['active_workday_without_duty'])}"
        )
        for row in report["active_workday_without_duty"]:
            self.stdout.write(f"  {row}")
        self.stdout.write(
            f"active_duty_inactive_workday: {len(report['active_duty_inactive_workday'])}"
        )
        for row in report["active_duty_inactive_workday"]:
            self.stdout.write(f"  {row}")
        self.stdout.write(
            f"active_worklog_without_duty: {len(report['active_worklog_without_duty'])}"
        )
        for row in report["active_worklog_without_duty"]:
            self.stdout.write(f"  {row}")
        if apply:
            self.stdout.write(self.style.SUCCESS(f"Repairs applied: {len(report['repairs'])}"))
            for line in report["repairs"]:
                self.stdout.write(f"  {line}")
        else:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to repair.")
            )
