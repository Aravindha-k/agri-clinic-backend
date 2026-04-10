import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    CropIssue,
    District,
    Farmer,
    FarmerField,
    FieldCrop,
    ProblemCategory,
    Recommendation,
    Village,
)
from notifications.models import Notification
from visits.models import Visit


class Command(BaseCommand):
    help = "Safe reset + production-like demo data seed for Agri Clinic"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Starting safe reset..."))
        self._safe_reset_demo_data()

        self.stdout.write(self.style.WARNING("Creating master data..."))
        districts, villages = self._create_master_data()

        self.stdout.write(self.style.WARNING("Creating employees..."))
        employees = self._create_employees(districts, villages)

        self.stdout.write(self.style.WARNING("Creating farmers + field crops..."))
        farmers, fields = self._create_farmers_and_crops(districts, villages, employees)

        self.stdout.write(self.style.WARNING("Creating visits..."))
        visits = self._create_visits(farmers, employees)

        self.stdout.write(self.style.WARNING("Creating crop issues..."))
        issues = self._create_issues(visits)

        self.stdout.write(self.style.WARNING("Creating recommendations..."))
        recommendations = self._create_recommendations(issues, employees)

        self._validate()

        self.stdout.write(self.style.SUCCESS("\nDemo dataset seeded successfully."))
        self.stdout.write(
            f"Districts: {District.objects.filter(name__in=['Coimbatore','Erode','Salem']).count()}"
        )
        self.stdout.write(
            f"Villages (requested set): {Village.objects.filter(name__in=['Pollachi','Gobichettipalayam','Mettur','Annur','Bhavani']).count()}"
        )
        self.stdout.write(f"Problem Categories: {ProblemCategory.objects.count()}")
        self.stdout.write(f"Employees (created/updated): {len(employees)}")
        self.stdout.write(f"Farmers: {len(farmers)}")
        self.stdout.write(f"Farmer Fields: {len(fields)}")
        self.stdout.write(f"Visits: {len(visits)}")
        self.stdout.write(f"Crop Issues: {len(issues)}")
        self.stdout.write(f"Recommendations: {len(recommendations)}")

    def _safe_reset_demo_data(self):
        Notification.objects.all().delete()
        Recommendation.objects.all().delete()
        CropIssue.objects.all().delete()
        Visit.objects.all().delete()
        FieldCrop.objects.all().delete()
        FarmerField.objects.all().delete()
        Farmer.objects.all().delete()
        ProblemCategory.objects.all().delete()
        Crop.objects.all().delete()

        # Keep admin/superusers. Remove only non-staff employee profiles and users.
        EmployeeProfile.objects.filter(
            user__is_staff=False, user__is_superuser=False
        ).delete()
        User.objects.filter(is_staff=False, is_superuser=False).delete()

    def _create_master_data(self):
        district_map = {}
        for name in ["Coimbatore", "Erode", "Salem"]:
            district_map[name], _ = District.objects.get_or_create(name=name)

        village_to_district = {
            "Pollachi": "Coimbatore",
            "Annur": "Coimbatore",
            "Gobichettipalayam": "Erode",
            "Bhavani": "Erode",
            "Mettur": "Salem",
        }
        village_map = {}
        for v_name, d_name in village_to_district.items():
            village, _ = Village.objects.get_or_create(
                name=v_name,
                defaults={"district": district_map[d_name]},
            )
            if village.district_id != district_map[d_name].id:
                village.district = district_map[d_name]
                village.save(update_fields=["district"])
            village_map[v_name] = village

        for cat in [
            "Pest Attack",
            "Leaf Yellowing",
            "Nutrient Deficiency",
            "Fungal Disease",
            "Water Stress",
        ]:
            ProblemCategory.objects.create(name=cat, description=f"{cat} related issue")

        crop_specs = [
            ("Paddy", "Nel", "Oryza sativa", "cereal", "kharif"),
            ("Coconut", "Thengai", "Cocos nucifera", "commercial", "annual"),
            ("Sugarcane", "Karumbu", "Saccharum officinarum", "commercial", "annual"),
            ("Banana", "Vazhai", "Musa acuminata", "fruit", "annual"),
            ("Tomato", "Thakkali", "Solanum lycopersicum", "vegetable", "rabi"),
        ]
        for name_en, name_ta, sci, category, season in crop_specs:
            Crop.objects.create(
                name_en=name_en,
                name_ta=name_ta,
                scientific_name=sci,
                crop_category=category,
                typical_season=season,
                is_active=True,
            )

        return district_map, village_map

    def _create_employees(self, districts, villages):
        records = [
            ("Aravind Kumar", "9876543210", "Coimbatore", "Pollachi", "EMP-101"),
            ("Prakash Raj", "9123456780", "Erode", "Gobichettipalayam", "EMP-102"),
            ("Suresh Babu", "9012345678", "Salem", "Mettur", "EMP-103"),
        ]
        users = []
        for full_name, phone, district_name, village_name, emp_id in records:
            first, last = self._split_name(full_name)
            username = f"{first.lower()}.{last.lower()}"
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "is_staff": False,
                    "is_superuser": False,
                    "is_active": True,
                    "email": f"{username}@kavyaagri.demo",
                },
            )
            user.first_name = first
            user.last_name = last
            user.is_active = True
            user.save(update_fields=["first_name", "last_name", "is_active"])
            user.set_password("Demo@123")
            user.save(update_fields=["password"])

            profile, _ = EmployeeProfile.objects.get_or_create(
                user=user,
                defaults={
                    "employee_id": emp_id,
                    "phone": phone,
                    "role": "FieldAgent",
                    "district": districts[district_name],
                    "village": villages[village_name],
                    "is_active_employee": True,
                    "can_login": True,
                },
            )
            profile.employee_id = emp_id
            profile.phone = phone
            profile.role = "FieldAgent"
            profile.district = districts[district_name]
            profile.village = villages[village_name]
            profile.is_active_employee = True
            profile.can_login = True
            profile.save()

            users.append(user)

        return users

    def _create_farmers_and_crops(self, districts, villages, employees):
        farmer_specs = [
            (
                "Ramesh Gounder",
                "9000001001",
                "Coimbatore",
                "Pollachi",
                Decimal("3.20"),
                "Paddy",
            ),
            (
                "Selvi Ammal",
                "9000001002",
                "Erode",
                "Gobichettipalayam",
                Decimal("2.80"),
                "Coconut",
            ),
            ("Murugan", "9000001003", "Salem", "Mettur", Decimal("4.50"), "Sugarcane"),
            (
                "Lakshmi Narayanan",
                "9000001004",
                "Coimbatore",
                "Annur",
                Decimal("3.75"),
                "Banana",
            ),
            ("Kannan", "9000001005", "Erode", "Bhavani", Decimal("2.40"), "Tomato"),
            (
                "Perumal",
                "9000001006",
                "Coimbatore",
                "Pollachi",
                Decimal("4.10"),
                "Coconut",
            ),
            ("Meenakshi", "9000001007", "Erode", "Bhavani", Decimal("2.60"), "Paddy"),
            (
                "Rajendran",
                "9000001008",
                "Salem",
                "Mettur",
                Decimal("3.90"),
                "Sugarcane",
            ),
            ("Chitra", "9000001009", "Coimbatore", "Annur", Decimal("2.20"), "Tomato"),
            (
                "Mani",
                "9000001010",
                "Erode",
                "Gobichettipalayam",
                Decimal("4.30"),
                "Banana",
            ),
        ]

        crop_by_name = {c.name_en: c for c in Crop.objects.all()}

        farmers = []
        fields = []
        for idx, (
            name,
            phone,
            district_name,
            village_name,
            land_size,
            crop_name,
        ) in enumerate(farmer_specs):
            assigned_emp = employees[idx % len(employees)]
            farmer = Farmer.objects.create(
                name=name,
                phone=phone,
                district=districts[district_name],
                village=villages[village_name],
                address=f"{village_name}, {district_name}",
                gps_location=f"11.{200000 + idx},77.{300000 + idx}",
                total_land_area=land_size,
                irrigation_type=random.choice(["borewell", "canal", "drip", "rainfed"]),
                soil_type=random.choice(["red", "black", "alluvial", "loamy"]),
                assigned_employee=assigned_emp,
                created_by_employee=assigned_emp,
                is_active=True,
            )
            farmers.append(farmer)

            field = FarmerField.objects.create(
                farmer=farmer,
                land_name="Main Field",
                land_size=land_size,
                soil_type=farmer.soil_type,
                irrigation_type=farmer.irrigation_type,
                gps_location=farmer.gps_location,
                created_by_employee=assigned_emp,
            )
            fields.append(field)

            FieldCrop.objects.create(
                land=field,
                crop_name=crop_name,
                crop=crop_by_name[crop_name],
                sowing_date=date.today() - timedelta(days=45 + idx),
                crop_stage=random.choice(["Vegetative", "Flowering", "Maturity"]),
                is_active=True,
            )

        return farmers, fields

    def _create_visits(self, farmers, employees):
        visits = []
        for idx, farmer in enumerate(farmers):
            employee = random.choice(employees)
            visit = Visit.objects.create(
                employee=employee,
                visit_date=date.today() - timedelta(days=idx % 7),
                district=farmer.district,
                village=farmer.village,
                farmer_name=farmer.name,
                farmer_phone=farmer.phone,
                land_name="Main Field",
                land_area=float(farmer.total_land_area or 2.0),
                crop=FieldCrop.objects.filter(land__farmer=farmer).first().crop,
                crop_stage=random.choice(["Vegetative", "Flowering", "Maturity"]),
                notes=f"Routine field inspection for {farmer.name}",
                crop_health=random.choice(["healthy", "moderate", "stressed"]),
                status="completed",
            )
            visits.append(visit)
        return visits

    def _create_issues(self, visits):
        templates = [
            "Leaf Yellowing in Paddy",
            "Pest Attack in Coconut",
            "Fungal spots in Tomato",
            "Nutrient deficiency signs in Banana",
            "Water stress symptoms in Sugarcane",
            "Stem borer impact in Paddy",
            "Leaf curl observed in Tomato",
            "Root rot symptoms in Coconut",
            "Early blight signs in Tomato",
            "Shoot drying in Sugarcane",
            "Patchy yellowing in Banana",
            "Aphid infestation in Paddy",
        ]
        severities = ["low", "medium", "high"]
        statuses = ["open", "under_review", "resolved"]

        issues = []
        for idx, text in enumerate(templates):
            visit = visits[idx % len(visits)]
            issue = CropIssue.objects.create(
                visit=visit,
                crop=visit.crop,
                severity=severities[idx % len(severities)],
                status=statuses[idx % len(statuses)],
                description=text,
            )
            issues.append(issue)
        return issues

    def _create_recommendations(self, issues, employees):
        rec_templates = [
            (
                "Urea",
                "Neem Oil",
                "5ml per liter",
                "Spray during evening and monitor leaf color in 5 days.",
            ),
            (
                "NPK",
                "Chlorpyrifos",
                "2g per liter",
                "Apply in two rounds at 7-day interval.",
            ),
            (
                "Urea",
                "Neem Oil",
                "3ml per liter",
                "Combine with light irrigation next morning.",
            ),
            (
                "NPK",
                "Chlorpyrifos",
                "4ml per liter",
                "Use protective gear during spray.",
            ),
            (
                "Urea",
                "Neem Oil",
                "5ml per liter",
                "Avoid spraying during peak sunlight.",
            ),
        ]

        recommendations = []
        for idx, issue in enumerate(issues[:5]):
            fertilizer, pesticide, dosage, notes = rec_templates[idx]
            rec = Recommendation.objects.create(
                issue=issue,
                given_by=employees[idx % len(employees)],
                fertilizer=fertilizer,
                pesticide=pesticide,
                dosage=dosage,
                notes=notes,
            )
            issue.status = "resolved"
            issue.save(update_fields=["status"])
            recommendations.append(rec)
        return recommendations

    def _validate(self):
        assert Farmer.objects.count() == 10, "Expected 10 farmers"
        assert Visit.objects.count() >= 10, "Expected at least 10 visits"
        assert 10 <= CropIssue.objects.count() <= 15, "Expected 10-15 issues"
        assert Recommendation.objects.count() == 5, "Expected exactly 5 recommendations"

        bad_visits = Visit.objects.filter(employee__isnull=True).count()
        bad_issues = CropIssue.objects.filter(visit__isnull=True).count()
        bad_recs = Recommendation.objects.filter(issue__isnull=True).count()
        bad_fields = FarmerField.objects.filter(farmer__isnull=True).count()

        if any([bad_visits, bad_issues, bad_recs, bad_fields]):
            raise ValueError(
                "FK validation failed: "
                f"bad_visits={bad_visits}, bad_issues={bad_issues}, bad_recs={bad_recs}, bad_fields={bad_fields}"
            )

    def _split_name(self, full_name):
        parts = full_name.strip().split(" ")
        if len(parts) == 1:
            return parts[0], "agent"
        return parts[0], parts[-1]
