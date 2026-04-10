from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import EmployeeProfile
from masters.models import Crop, CropIssue, District, Farmer, Village
from visits.models import Visit


class Command(BaseCommand):
    help = "Create sample Crop Issues data for admin UI and crop-issues APIs"

    @transaction.atomic
    def handle(self, *args, **options):
        user = self._ensure_employee()
        farmer = self._ensure_farmer(user)
        crop = self._ensure_crop()
        visit = self._ensure_visit(user, farmer, crop)

        issue_templates = [
            {
                "title": "Leaf Yellowing",
                "description": "Leaves turning yellow in lower section",
                "severity": "medium",
                "status": "open",
            },
            {
                "title": "Pest Attack",
                "description": "Leaf-eating insects observed on multiple plants",
                "severity": "high",
                "status": "under_review",  # IN_PROGRESS equivalent
            },
            {
                "title": "Slow Growth",
                "description": "Plant growth is below expected stage for the season",
                "severity": "low",
                "status": "resolved",
            },
            {
                "title": "Stem Rot",
                "description": "Early signs of stem rot in wet patches",
                "severity": "high",
                "status": "open",
            },
            {
                "title": "Nutrient Deficiency",
                "description": "Pale foliage and uneven growth indicate nutrient imbalance",
                "severity": "medium",
                "status": "under_review",  # IN_PROGRESS equivalent
            },
        ]

        created_count = 0
        for idx, template in enumerate(issue_templates):
            composed_description = f"{template['title']}: {template['description']}"
            issue, created = CropIssue.objects.get_or_create(
                visit=visit,
                crop=crop,
                description=composed_description,
                defaults={
                    "severity": template["severity"],
                    "status": template["status"],
                },
            )
            if not created:
                issue.severity = template["severity"]
                issue.status = template["status"]
                issue.save(update_fields=["severity", "status"])
            created_count += 1

            # Spread timestamps slightly to improve UI ordering clarity.
            CropIssue.objects.filter(pk=issue.pk).update(
                created_at=visit.created_at + timedelta(minutes=idx + 1)
            )

        self.stdout.write(self.style.SUCCESS("Sample Crop Issues setup complete."))
        self.stdout.write(f"Employee user id: {user.id}")
        self.stdout.write(f"Farmer id: {farmer.id}")
        self.stdout.write(f"Crop id: {crop.id}")
        self.stdout.write(f"Visit id: {visit.id}")
        self.stdout.write(f"Crop issues ensured: {created_count}")
        self.stdout.write(
            "Endpoints: /api/v1/crop-issues/ | /api/v1/issues/ | /api/v1/admin/crop-issues/ | /api/v1/admin/issues/"
        )

    def _ensure_employee(self):
        User = get_user_model()

        existing = (
            User.objects.filter(is_staff=False)
            .select_related("employee_profile")
            .order_by("id")
            .first()
        )
        if existing and hasattr(existing, "employee_profile"):
            return existing

        user, _ = User.objects.get_or_create(
            username="sample_employee",
            defaults={
                "first_name": "Sample",
                "last_name": "Employee",
                "is_staff": False,
                "is_active": True,
            },
        )
        if not user.has_usable_password():
            user.set_password("sample123")
            user.save(update_fields=["password"])

        profile, _ = EmployeeProfile.objects.get_or_create(
            user=user,
            defaults={
                "employee_id": "KAC-9001",
                "phone": "9000000001",
                "role": "FieldAgent",
                "is_active_employee": True,
                "can_login": True,
            },
        )
        if not profile.employee_id:
            profile.employee_id = "KAC-9001"
            profile.save(update_fields=["employee_id"])

        return user

    def _ensure_farmer(self, employee):
        district, _ = District.objects.get_or_create(name="Sample District")
        village, _ = Village.objects.get_or_create(
            name="Sample Village",
            defaults={"district": district},
        )
        if village.district_id is None:
            village.district = district
            village.save(update_fields=["district"])

        farmer, _ = Farmer.objects.get_or_create(
            phone="9000001001",
            defaults={
                "name": "Sample Farmer",
                "district": district,
                "village": village,
                "address": "1 Demo Farm Road",
                "gps_location": "11.1271,78.6569",
                "total_land_area": 2.50,
                "irrigation_type": "drip",
                "soil_type": "loamy",
                "assigned_employee": employee,
                "created_by_employee": employee,
                "is_active": True,
            },
        )
        changed = False
        if farmer.assigned_employee_id is None:
            farmer.assigned_employee = employee
            changed = True
        if farmer.created_by_employee_id is None:
            farmer.created_by_employee = employee
            changed = True
        if changed:
            farmer.save(update_fields=["assigned_employee", "created_by_employee"])
        return farmer

    def _ensure_crop(self):
        crop, _ = Crop.objects.get_or_create(
            name_en="Paddy",
            defaults={
                "name_ta": "Nel",
                "scientific_name": "Oryza sativa",
                "crop_category": "cereal",
                "typical_season": "kharif",
                "is_active": True,
            },
        )
        if not crop.name_ta:
            crop.name_ta = "Nel"
            crop.save(update_fields=["name_ta"])
        return crop

    def _ensure_visit(self, employee, farmer, crop):
        visit, _ = Visit.objects.get_or_create(
            employee=employee,
            farmer_phone=farmer.phone,
            crop=crop,
            defaults={
                "visit_date": date.today(),
                "latitude": 11.1271,
                "longitude": 78.6569,
                "district": farmer.district,
                "village": farmer.village,
                "farmer_name": farmer.name,
                "land_name": "Main Plot",
                "land_area": float(farmer.total_land_area or 2.5),
                "crop_stage": "Vegetative",
                "notes": "Sample visit for admin crop issue UI",
                "status": "completed",
            },
        )

        updates = []
        if not visit.farmer_name:
            visit.farmer_name = farmer.name
            updates.append("farmer_name")
        if not visit.district_id and farmer.district_id:
            visit.district = farmer.district
            updates.append("district")
        if not visit.village_id and farmer.village_id:
            visit.village = farmer.village
            updates.append("village")
        if updates:
            visit.save(update_fields=updates)

        return visit
