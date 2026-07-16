"""Dry-run audit of visit consistency (Phase 5)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, F

from masters.models import Farmer, FarmerActivity
from tracking.models import EmployeeRoutePoint
from visits.models import Visit, VisitAttachment, VisitMedia


class Command(BaseCommand):
    help = (
        "Audit visit consistency: local_sync_id duplicates, route points, "
        "duty ownership, media, FarmerActivity. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Apply safe deterministic repairs only "
                "(delete extra VISIT route points per visit; "
                "delete extra FarmerActivity VISIT_COMPLETED rows)."
            ),
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        report = {
            "visits_total": Visit.objects.count(),
            "duplicate_local_sync_groups": 0,
            "duplicate_local_sync_extra_rows": 0,
            "wrong_duty_employee": 0,
            "workday_without_duty": 0,
            "invalid_coordinates": 0,
            "duplicate_visit_route_points": 0,
            "duplicate_media_client_upload_groups": 0,
            "orphan_media": 0,
            "orphan_attachments": 0,
            "media_attachment_overlap_visits": 0,
            "farmer_activity_visit_duplicates": 0,
            "ambiguous_farmer_phones": 0,
            "repaired_route_points": 0,
            "repaired_activities": 0,
        }

        sync_groups = list(
            Visit.objects.exclude(local_sync_id__isnull=True)
            .exclude(local_sync_id="")
            .values("employee_id", "local_sync_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["duplicate_local_sync_groups"] = len(sync_groups)
        report["duplicate_local_sync_extra_rows"] = sum(g["c"] - 1 for g in sync_groups)

        report["wrong_duty_employee"] = (
            Visit.objects.filter(duty_session__isnull=False)
            .exclude(duty_session__user_id=F("employee_id"))
            .count()
        )
        report["workday_without_duty"] = Visit.objects.filter(
            workday__isnull=False, duty_session__isnull=True
        ).count()

        invalid = 0
        for v in (
            Visit.objects.exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .only("id", "latitude", "longitude")
            .iterator()
        ):
            lat, lng = v.latitude, v.longitude
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                invalid += 1
        report["invalid_coordinates"] = invalid

        route_dupes = list(
            EmployeeRoutePoint.objects.filter(
                point_type=EmployeeRoutePoint.POINT_VISIT,
                visit_id__isnull=False,
            )
            .values("visit_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["duplicate_visit_route_points"] = sum(g["c"] - 1 for g in route_dupes)

        media_dupes = (
            VisitMedia.objects.exclude(client_upload_id="")
            .values("visit_id", "client_upload_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["duplicate_media_client_upload_groups"] = media_dupes.count()

        visit_ids = set(Visit.objects.values_list("id", flat=True))
        report["orphan_media"] = VisitMedia.objects.exclude(
            visit_id__in=visit_ids
        ).count()
        report["orphan_attachments"] = VisitAttachment.objects.exclude(
            visit_id__in=visit_ids
        ).count()

        media_visits = set(
            VisitMedia.objects.values_list("visit_id", flat=True).distinct()
        )
        attachment_visits = set(
            VisitAttachment.objects.values_list("visit_id", flat=True).distinct()
        )
        report["media_attachment_overlap_visits"] = len(
            media_visits & attachment_visits
        )

        activity_dupes = list(
            FarmerActivity.objects.filter(activity_type="VISIT_COMPLETED")
            .values("farmer_id", "reference_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["farmer_activity_visit_duplicates"] = sum(
            g["c"] - 1 for g in activity_dupes
        )

        phone_counts = (
            Farmer.objects.exclude(phone="")
            .exclude(phone__isnull=True)
            .values("phone")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        report["ambiguous_farmer_phones"] = phone_counts.count()

        self.stdout.write("=== Visit consistency audit ===")
        for key, value in report.items():
            self.stdout.write(f"{key}: {value}")

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "No changes made. Re-run with --apply for safe "
                    "deterministic repairs only."
                )
            )
            return

        deleted_routes = 0
        for group in route_dupes:
            qs = EmployeeRoutePoint.objects.filter(
                visit_id=group["visit_id"],
                point_type=EmployeeRoutePoint.POINT_VISIT,
            ).order_by("id")
            keep = qs.first()
            if keep:
                deleted_routes += qs.exclude(pk=keep.pk).delete()[0]
        report["repaired_route_points"] = deleted_routes

        deleted_acts = 0
        for group in activity_dupes:
            qs = FarmerActivity.objects.filter(
                farmer_id=group["farmer_id"],
                activity_type="VISIT_COMPLETED",
                reference_id=group["reference_id"],
            ).order_by("id")
            keep = qs.first()
            if keep:
                deleted_acts += qs.exclude(pk=keep.pk).delete()[0]
        report["repaired_activities"] = deleted_acts

        self.stdout.write(
            self.style.SUCCESS(
                f"Applied repairs: route_points={deleted_routes}, "
                f"activities={deleted_acts}"
            )
        )
        self.stdout.write(
            "Note: ambiguous farmers / local_sync conflicts are not auto-resolved."
        )
