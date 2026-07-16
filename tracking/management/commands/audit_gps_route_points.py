"""Audit / repair GPS route-point data (Phase 4).

Default is dry-run. Pass --apply to perform safe backfills / deduplication.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count

from tracking.models import EmployeeRoutePoint, LocationLog


class Command(BaseCommand):
    help = (
        "Audit EmployeeRoutePoint / LocationLog for duplicates, missing duty, "
        "invalid coordinates, and missing client_point_id. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply safe repairs (dedupe by client_point_id; do not invent ids).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        report = {
            "route_points_total": EmployeeRoutePoint.objects.count(),
            "location_logs_total": LocationLog.objects.count(),
            "missing_client_point_id": 0,
            "invalid_coordinates": 0,
            "client_id_duplicate_groups": 0,
            "client_id_duplicate_rows": 0,
            "historical_coord_time_duplicates": 0,
            "deleted_on_apply": 0,
            "backfilled_client_ids": 0,
        }

        missing_qs = EmployeeRoutePoint.objects.filter(client_point_id__isnull=True)
        report["missing_client_point_id"] = missing_qs.count()

        invalid = 0
        for row in EmployeeRoutePoint.objects.only("id", "latitude", "longitude").iterator(
            chunk_size=500
        ):
            lat = float(row.latitude)
            lng = float(row.longitude)
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                invalid += 1
        report["invalid_coordinates"] = invalid

        # Duplicate client_point_id within a duty (should be impossible after constraint,
        # but useful for pre-migration / --apply cleanup).
        dup_groups = (
            EmployeeRoutePoint.objects.exclude(client_point_id__isnull=True)
            .exclude(client_point_id="")
            .values("duty_session_id", "client_point_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["client_id_duplicate_groups"] = dup_groups.count()
        deleted = 0
        for group in dup_groups:
            rows = list(
                EmployeeRoutePoint.objects.filter(
                    duty_session_id=group["duty_session_id"],
                    client_point_id=group["client_point_id"],
                ).order_by("id")
            )
            report["client_id_duplicate_rows"] += len(rows)
            keep, extras = rows[0], rows[1:]
            if apply and extras:
                EmployeeRoutePoint.objects.filter(
                    pk__in=[r.pk for r in extras]
                ).delete()
                deleted += len(extras)
                self.stdout.write(
                    f"Deduped duty={group['duty_session_id']} "
                    f"client_point_id={group['client_point_id']} "
                    f"kept={keep.pk} removed={len(extras)}"
                )

        # Historical replay-ish: same duty + lat + lng + recorded_at
        hist = defaultdict(list)
        for row in EmployeeRoutePoint.objects.filter(
            point_type=EmployeeRoutePoint.POINT_GPS
        ).only(
            "id", "duty_session_id", "latitude", "longitude", "recorded_at"
        ).iterator(chunk_size=500):
            key = (
                row.duty_session_id,
                str(row.latitude),
                str(row.longitude),
                row.recorded_at.isoformat() if row.recorded_at else None,
            )
            hist[key].append(row.id)
        hist_dups = sum(1 for ids in hist.values() if len(ids) > 1)
        report["historical_coord_time_duplicates"] = hist_dups

        report["deleted_on_apply"] = deleted

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(self.style.NOTICE(f"=== GPS audit ({mode}) ===="))
        for key, value in report.items():
            self.stdout.write(f"{key}: {value}")

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "No changes made. Re-run with --apply to delete "
                    "client_point_id duplicate extras only."
                )
            )
            self.stdout.write(
                "Note: missing client_point_id is not backfilled automatically "
                "(unsafe for historical rows)."
            )
        else:
            self.stdout.write(self.style.SUCCESS("Apply complete."))
