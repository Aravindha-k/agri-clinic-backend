"""
Seed one submitted field visit per active farmer (demo data for admin UI).

Idempotent: uses local_sync_id agri-demo-seed-v1-farmer-{farmer_id}
"""

from __future__ import annotations

from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import EmployeeProfile
from farmers.helpers import active_farmers_queryset
from masters.models import Crop
from visits.models import Visit
from visits.submitted import submitted_visits_qs, visit_has_submitted_details

SEED_PREFIX = "agri-demo-seed-v1-farmer-"
# Tamil Nadu-ish base coordinate; per-farmer offset for variety
BASE_LAT = 11.0168
BASE_LNG = 76.9558


def demo_sync_id(farmer_id: int) -> str:
    return f"{SEED_PREFIX}{farmer_id}"


def planned_demo_visits():
    """Rows to create: farmer, employee, crop, lat, lng, visit_date, sync_id."""
    farmers = list(
        active_farmers_queryset()
        .select_related("district", "village")
        .order_by("id")
    )
    employees = list(
        EmployeeProfile.objects.filter(
            is_active_employee=True,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("employee_id")
    )
    crops = list(Crop.objects.filter(is_active=True).order_by("id"))
    if not farmers:
        return [], "No active farmers found."
    if not employees:
        return [], "No active employees found."
    if not crops:
        return [], "No active crops found."

    existing_sync_ids = set(
        Visit.objects.filter(local_sync_id__startswith=SEED_PREFIX).values_list(
            "local_sync_id", flat=True
        )
    )
    today = timezone.localdate()
    plans = []
    for idx, farmer in enumerate(farmers):
        sync_id = demo_sync_id(farmer.id)
        if sync_id in existing_sync_ids:
            continue
        employee = employees[idx % len(employees)]
        crop = crops[idx % len(crops)]
        offset = (farmer.id % 50) * 0.008
        lat = round(BASE_LAT + offset, 6)
        lng = round(BASE_LNG + (farmer.id % 30) * 0.008, 6)
        visit_date = today - timedelta(days=idx % 14)
        plans.append(
            {
                "farmer": farmer,
                "employee": employee.user,
                "crop": crop,
                "latitude": lat,
                "longitude": lng,
                "visit_date": visit_date,
                "local_sync_id": sync_id,
            }
        )
    return plans, None


def _invalidate_caches() -> None:
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception:
        pass
    try:
        from farmers.services import invalidate_farmers_list_cache

        invalidate_farmers_list_cache()
    except Exception:
        pass


class Command(BaseCommand):
    help = (
        "Create one submitted visit per active farmer (idempotent demo seed). "
        "Dry-run by default; pass --confirm to insert."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview planned visits (default without --confirm).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Insert planned visits.",
        )

    def handle(self, *args, **options):
        dry_run = not options["confirm"]
        plans, err = planned_demo_visits()
        if err:
            self.stdout.write(self.style.ERROR(err))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Real demo visit seed"))
        self.stdout.write(f"  Active farmers: {active_farmers_queryset().count()}")
        self.stdout.write(f"  Submitted visits now: {submitted_visits_qs().count()}")
        self.stdout.write(f"  Visits to create: {len(plans)}")
        self.stdout.write("")

        if not plans:
            self.stdout.write(
                self.style.SUCCESS(
                    "Nothing to create — every active farmer already has a demo seed visit."
                )
            )
            return

        for p in plans:
            farmer = p["farmer"]
            self.stdout.write(
                f"  {p['local_sync_id']}: farmer={farmer.id} {farmer.name!r} "
                f"employee={p['employee'].username} crop={p['crop'].name_en} "
                f"date={p['visit_date']} ({p['latitude']}, {p['longitude']})"
            )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("Dry-run: no rows inserted. Use --confirm to apply.")
            )
            return

        created = 0
        with transaction.atomic():
            for p in plans:
                if Visit.objects.filter(local_sync_id=p["local_sync_id"]).exists():
                    continue
                farmer = p["farmer"]
                visit = Visit.objects.create(
                    employee=p["employee"],
                    farmer=farmer,
                    farmer_name=farmer.name,
                    farmer_phone=farmer.phone,
                    district=farmer.district,
                    village=farmer.village,
                    crop=p["crop"],
                    latitude=p["latitude"],
                    longitude=p["longitude"],
                    visit_date=p["visit_date"],
                    visit_time=time(10, 30),
                    local_sync_id=p["local_sync_id"],
                    notes="Demo field visit (seed_real_demo_visits).",
                )
                if not visit_has_submitted_details(visit):
                    raise RuntimeError(f"Seed visit failed validation: {visit.pk}")
                created += 1

        _invalidate_caches()
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Created {created} submitted demo visit(s).")
        )
        self.stdout.write(
            f"  Submitted visits now: {submitted_visits_qs().count()}"
        )
