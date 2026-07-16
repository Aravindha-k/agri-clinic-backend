"""Dry-run audit of duty day-map data consistency."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, F

from tracking.models import DutySession, EmployeeRoutePoint, LocationLog
from tracking.route_utils import is_valid_coordinate
from visits.models import Visit
from visits.submitted import submitted_visits_qs


class Command(BaseCommand):
    help = (
        "Audit DutySession map data: missing routes, invalid coords, "
        "duplicate visit points, legacy-only routes. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Reserved; only deterministic safe repairs if implemented.",
        )

    def handle(self, *args, **options):
        report = {
            "duties_total": DutySession.objects.count(),
            "duties_without_route_points": 0,
            "route_points_without_duty": 0,
            "cross_user_route_points": 0,
            "duplicate_visit_route_points": 0,
            "visits_on_duty_missing_coords": 0,
            "visits_on_duty_missing_visit_route_point": 0,
            "invalid_route_coordinates": 0,
            "invalid_visit_coordinates": 0,
            "completed_duties_no_end_signal": 0,
            "legacy_only_route_duties": 0,
            "multiple_start_markers": 0,
            "multiple_end_markers": 0,
        }

        duty_ids_with_routes = set(
            EmployeeRoutePoint.objects.values_list("duty_session_id", flat=True).distinct()
        )
        all_duty_ids = set(DutySession.objects.values_list("id", flat=True))
        report["duties_without_route_points"] = len(all_duty_ids - duty_ids_with_routes)

        report["route_points_without_duty"] = EmployeeRoutePoint.objects.filter(
            duty_session__isnull=True
        ).count()

        report["cross_user_route_points"] = (
            EmployeeRoutePoint.objects.exclude(user_id=F("duty_session__user_id")).count()
        )

        visit_dupes = (
            EmployeeRoutePoint.objects.filter(
                point_type=EmployeeRoutePoint.POINT_VISIT,
                visit_id__isnull=False,
            )
            .values("visit_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["duplicate_visit_route_points"] = sum(g["c"] - 1 for g in visit_dupes)

        duty_visits = submitted_visits_qs().filter(duty_session_id__isnull=False)
        report["visits_on_duty_missing_coords"] = duty_visits.filter(
            latitude__isnull=True
        ).count() + duty_visits.filter(longitude__isnull=True).exclude(
            latitude__isnull=True
        ).count()

        visit_ids_with_rp = set(
            EmployeeRoutePoint.objects.filter(
                point_type=EmployeeRoutePoint.POINT_VISIT,
                visit_id__isnull=False,
            ).values_list("visit_id", flat=True)
        )
        report["visits_on_duty_missing_visit_route_point"] = (
            duty_visits.exclude(id__in=visit_ids_with_rp)
            .exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .count()
        )

        invalid_route = 0
        for row in EmployeeRoutePoint.objects.only("id", "latitude", "longitude").iterator(
            chunk_size=500
        ):
            try:
                lat, lng = float(row.latitude), float(row.longitude)
            except (TypeError, ValueError):
                invalid_route += 1
                continue
            if not is_valid_coordinate(lat, lng):
                invalid_route += 1
        report["invalid_route_coordinates"] = invalid_route

        invalid_visit = 0
        for v in (
            Visit.objects.exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .only("id", "latitude", "longitude")
            .iterator(chunk_size=500)
        ):
            if not is_valid_coordinate(v.latitude, v.longitude):
                invalid_visit += 1
        report["invalid_visit_coordinates"] = invalid_visit

        completed = DutySession.objects.filter(is_active=False)
        no_end = 0
        for duty in completed.only("id", "end_time").iterator():
            has_end_pt = EmployeeRoutePoint.objects.filter(
                duty_session_id=duty.pk, point_type="end"
            ).exists()
            has_any = duty.pk in duty_ids_with_routes
            if not has_end_pt and not has_any:
                no_end += 1
        report["completed_duties_no_end_signal"] = no_end

        legacy_only = 0
        for duty_id, user_id, workday_id, ddate in DutySession.objects.values_list(
            "id", "user_id", "workday_id", "date"
        ):
            if duty_id in duty_ids_with_routes:
                continue
            logs = LocationLog.objects.filter(user_id=user_id)
            if workday_id:
                if logs.filter(workday_id=workday_id).exists():
                    legacy_only += 1
            elif logs.filter(recorded_at__date=ddate).exists():
                legacy_only += 1
        report["legacy_only_route_duties"] = legacy_only

        start_multi = (
            EmployeeRoutePoint.objects.filter(point_type="start")
            .values("duty_session_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        end_multi = (
            EmployeeRoutePoint.objects.filter(point_type="end")
            .values("duty_session_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["multiple_start_markers"] = start_multi.count()
        report["multiple_end_markers"] = end_multi.count()

        self.stdout.write("=== Duty day-map data audit (DRY-RUN) ===")
        for key, value in report.items():
            self.stdout.write(f"{key}: {value}")
        if options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "No automatic repairs in this phase. Ambiguous rows left untouched."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING("No changes made. Dry-run only.")
            )
