"""Audit live-tracking state integrity."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracking.models import DutySession, EmployeeLiveLocation


class Command(BaseCommand):
    help = "Audit EmployeeLiveLocation / active-duty consistency"

    def handle(self, *args, **options):
        now = timezone.now()
        report = {
            "active_duties": DutySession.objects.filter(is_active=True).count(),
            "live_rows": EmployeeLiveLocation.objects.count(),
            "active_duty_missing_live": 0,
            "live_linked_inactive_duty": 0,
            "invalid_coordinates": 0,
            "future_heartbeat": 0,
            "null_coords_active": 0,
        }

        active = list(
            DutySession.objects.filter(is_active=True).values_list("pk", "user_id")
        )
        live_by_user = {
            row.user_id: row for row in EmployeeLiveLocation.objects.all()
        }
        for _duty_id, user_id in active:
            live = live_by_user.get(user_id)
            if live is None:
                report["active_duty_missing_live"] += 1
            elif live.latitude is None or live.longitude is None:
                report["null_coords_active"] += 1

        for live in EmployeeLiveLocation.objects.select_related("duty_session"):
            if live.duty_session_id and live.duty_session and not live.duty_session.is_active:
                report["live_linked_inactive_duty"] += 1
            if live.last_heartbeat_at and live.last_heartbeat_at > now + timedelta(
                minutes=10
            ):
                report["future_heartbeat"] += 1
            lat, lng = live.latitude, live.longitude
            if lat is not None and lng is not None:
                try:
                    if not (-90 <= float(lat) <= 90 and -180 <= float(lng) <= 180):
                        report["invalid_coordinates"] += 1
                except (TypeError, ValueError):
                    report["invalid_coordinates"] += 1
            elif lat is not None or lng is not None:
                report["invalid_coordinates"] += 1

        self.stdout.write(self.style.SUCCESS(str(report)))
        problems = (
            report["active_duty_missing_live"]
            + report["live_linked_inactive_duty"]
            + report["invalid_coordinates"]
            + report["future_heartbeat"]
        )
        if problems:
            self.stdout.write(self.style.WARNING(f"issues={problems}"))
            return
        self.stdout.write(self.style.SUCCESS("live_tracking_audit_ok"))
