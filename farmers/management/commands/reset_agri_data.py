import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    CropIssue,
    District,
    Farmer,
    FarmerActivity,
    FarmerField,
    FieldCrop,
    ProblemCategory,
    Recommendation,
    Village,
)
from visits.models import Visit, VisitMedia


class Command(BaseCommand):
    help = "Reset database and generate clean test data for frontend testing"

    def handle(self, *args, **options):
        self.stdout.write("=== Clearing existing data ===")
        self._clear_data()

        self.stdout.write("=== Creating master data ===")
        districts, villages = self._create_locations()
        crops = self._create_crops()
        categories = self._create_problem_categories()

        self.stdout.write("=== Creating employees ===")
        employees = self._create_employees(districts[0], villages)

        self.stdout.write("=== Creating farmers ===")
        farmers = self._create_farmers(districts[0], villages, employees)

        self.stdout.write("=== Creating fields ===")
        all_fields = self._create_fields(farmers, employees)

        self.stdout.write("=== Creating field crops ===")
        self._create_field_crops(all_fields, crops)

        self.stdout.write("=== Creating visits ===")
        visits = self._create_visits(
            farmers, all_fields, employees, villages, crops, categories
        )

        self.stdout.write("=== Creating crop issues ===")
        issues = self._create_issues(visits, crops, categories)

        self.stdout.write("=== Creating recommendations ===")
        self._create_recommendations(issues, employees)

        self.stdout.write("=== Creating visit media ===")
        self._create_visit_media(visits)

        self.stdout.write(
            self.style.SUCCESS(
                "\nDone! Test data generated successfully.\n"
                f"  Districts: {District.objects.count()}\n"
                f"  Villages:  {Village.objects.count()}\n"
                f"  Crops:     {Crop.objects.count()}\n"
                f"  Employees: {User.objects.filter(is_staff=False).count()}\n"
                f"  Farmers:   {Farmer.objects.count()}\n"
                f"  Fields:    {FarmerField.objects.count()}\n"
                f"  FieldCrops:{FieldCrop.objects.count()}\n"
                f"  Visits:    {Visit.objects.count()}\n"
                f"  Issues:    {CropIssue.objects.count()}\n"
                f"  Recs:      {Recommendation.objects.count()}\n"
                f"  Media:     {VisitMedia.objects.count()}\n"
            )
        )

    # ── STEP 1: Clear ────────────────────────────────────

    def _clear_data(self):
        models_in_order = [
            VisitMedia,
            Recommendation,
            CropIssue,
            Visit,
            FieldCrop,
            FarmerField,
            FarmerActivity,
            Farmer,
            ProblemCategory,
            Crop,
            Village,
            District,
        ]
        for model in models_in_order:
            count = model.objects.all().delete()[0]
            self.stdout.write(f"  Deleted {count} {model.__name__}")

        # Remove test employee users (non-staff, non-superuser)
        deleted = User.objects.filter(is_staff=False, is_superuser=False).delete()[0]
        self.stdout.write(f"  Deleted {deleted} test users")

    # ── STEP 2: Locations ────────────────────────────────

    def _create_locations(self):
        district_data = [
            (
                "Salem",
                [
                    ("Omalur", ["Pommalappatti", "Karuppur", "Tharamangalam"]),
                    ("Mettur", ["Nallampatti", "Kolathur", "Mecheri"]),
                    ("Attur", ["Narasingapuram", "Thalaivasal", "Gangavalli"]),
                ],
            ),
            (
                "Erode",
                [
                    ("Gobichettipalayam", ["Kavundapadi", "Nambiyur", "Anthiyur"]),
                    ("Bhavani", ["Salangapalayam", "Kodumudi", "Sivagiri"]),
                ],
            ),
            (
                "Namakkal",
                [
                    ("Tiruchengode", ["Pallipalayam", "Mohanur", "Vennandur"]),
                    ("Rasipuram", ["Sendamangalam", "Namagiripettai", "Kolli Hills"]),
                ],
            ),
        ]

        districts, villages = [], []
        for d_name, taluk_list in district_data:
            d = District.objects.create(name=d_name)
            districts.append(d)
            for t_name, village_list in taluk_list:
                for v_name in village_list:
                    v = Village.objects.create(district=d, name=v_name)
                    villages.append(v)

        self.stdout.write(
            f"  Created {len(districts)} districts, " f"{len(villages)} villages"
        )
        return districts, villages

    # ── STEP 2b: Crops ───────────────────────────────────

    def _create_crops(self):
        crop_data = [
            ("Paddy", "Oryza sativa", "cereal", "kharif"),
            ("Banana", "Musa acuminata", "fruit", "annual"),
            ("Coconut", "Cocos nucifera", "commercial", "annual"),
            ("Sugarcane", "Saccharum officinarum", "commercial", "annual"),
            ("Groundnut", "Arachis hypogaea", "oilseed", "kharif"),
            ("Maize", "Zea mays", "cereal", "rabi"),
            ("Tomato", "Solanum lycopersicum", "vegetable", "rabi"),
            ("Turmeric", "Curcuma longa", "spice", "kharif"),
        ]
        crops = []
        for name, sci, cat, season in crop_data:
            c = Crop.objects.create(
                name=name,
                scientific_name=sci,
                crop_category=cat,
                typical_season=season,
            )
            crops.append(c)
        self.stdout.write(f"  Created {len(crops)} crops")
        return crops

    # ── STEP 2c: Problem categories ──────────────────────

    def _create_problem_categories(self):
        names = [
            "Pest Attack",
            "Fungal Disease",
            "Nutrient Deficiency",
            "Water Stress",
            "Weed Infestation",
            "Soil Degradation",
        ]
        cats = [ProblemCategory.objects.create(name=n) for n in names]
        self.stdout.write(f"  Created {len(cats)} problem categories")
        return cats

    # ── STEP 3: Employees ────────────────────────────────

    def _create_employees(self, district, villages):
        employee_data = [
            ("ravi", "Ravi", "Kumar", "9876543210", "EMP-001", "FieldAgent"),
            ("kumar", "Kumar", "Selvam", "9876543211", "EMP-002", "FieldAgent"),
            ("manoj", "Manoj", "Pandian", "9876543212", "EMP-003", "Supervisor"),
        ]
        employees = []
        for uname, first, last, phone, emp_id, role in employee_data:
            user = User.objects.create_user(
                username=uname,
                first_name=first,
                last_name=last,
                password="testpass123",
                email=f"{uname}@agri.test",
            )
            EmployeeProfile.objects.create(
                user=user,
                employee_id=emp_id,
                phone=phone,
                role=role,
                district=district,
                village=random.choice(villages[:3]),
            )
            employees.append(user)
        self.stdout.write(f"  Created {len(employees)} employees")
        return employees

    # ── STEP 4: Farmers ──────────────────────────────────

    def _create_farmers(self, district, villages, employees):
        farmer_names = [
            ("Ramesh", "9944001001"),
            ("Suresh", "9944001002"),
            ("Mahesh", "9944001003"),
            ("Gopal", "9944001004"),
            ("Senthil", "9944001005"),
            ("Murugan", "9944001006"),
            ("Karthik", "9944001007"),
            ("Balaji", "9944001008"),
            ("Vignesh", "9944001009"),
            ("Arun", "9944001010"),
        ]
        soils = ["red", "black", "alluvial", "loamy"]
        irrigations = ["borewell", "canal", "drip", "rainfed"]

        farmers = []
        for i, (name, phone) in enumerate(farmer_names):
            village = villages[i % len(villages)]
            f = Farmer(
                name=name,
                phone=phone,
                district=district,
                village=village,
                address=f"{name}'s farm, {village.name}",
                gps_location=f"{11.6 + random.uniform(0, 0.5):.6f},{78.1 + random.uniform(0, 0.5):.6f}",
                total_land_area=Decimal(str(round(random.uniform(2, 15), 2))),
                soil_type=soils[i % len(soils)],
                irrigation_type=irrigations[i % len(irrigations)],
                assigned_employee=employees[i % len(employees)],
                created_by=employees[0],
            )
            f.save()
            farmers.append(f)
        self.stdout.write(f"  Created {len(farmers)} farmers")
        return farmers

    # ── STEP 5: Fields ───────────────────────────────────

    def _create_fields(self, farmers, employees):
        field_templates = [
            ("North Field", Decimal("3.50"), "red", "borewell"),
            ("South Field", Decimal("4.25"), "black", "canal"),
            ("East Plot", Decimal("2.75"), "alluvial", "drip"),
            ("West Plot", Decimal("5.00"), "loamy", "rainfed"),
        ]
        all_fields = []
        for farmer in farmers:
            for j in range(2):
                tpl = field_templates[(hash(farmer.name) + j) % len(field_templates)]
                ff = FarmerField.objects.create(
                    farmer=farmer,
                    field_name=tpl[0],
                    field_size=tpl[1],
                    soil_type=tpl[2],
                    irrigation_type=tpl[3],
                    created_by_employee=employees[0],
                )
                all_fields.append(ff)
        self.stdout.write(f"  Created {len(all_fields)} fields")
        return all_fields

    # ── STEP 6: Field crops ──────────────────────────────

    def _create_field_crops(self, fields, crops):
        seasons = ["kharif", "rabi", "zaid", "annual"]
        today = date.today()
        count = 0
        for field in fields:
            crop = random.choice(crops)
            sowing = today - timedelta(days=random.randint(30, 120))
            FieldCrop.objects.create(
                field=field,
                crop=crop,
                season=random.choice(seasons),
                sowing_date=sowing,
                expected_harvest_date=sowing + timedelta(days=random.randint(90, 180)),
            )
            count += 1
        self.stdout.write(f"  Created {count} field crops")

    # ── STEP 7: Visits ───────────────────────────────────

    def _create_visits(self, farmers, fields, employees, villages, crops, categories):
        conditions = ["healthy", "wilting", "pest-affected", "nutrient-deficient"]
        today = date.today()
        visits = []

        field_map = {}
        for f in fields:
            field_map.setdefault(f.farmer_id, []).append(f)

        for farmer in farmers:
            farmer_fields = field_map.get(farmer.pk, [])
            emp = farmer.assigned_employee or employees[0]
            for v_idx in range(2):
                field = (
                    farmer_fields[v_idx % len(farmer_fields)] if farmer_fields else None
                )
                visit_date = today - timedelta(days=random.randint(1, 60))
                crop = random.choice(crops)
                v = Visit.objects.create(
                    employee=emp,
                    farmer_name=farmer.name,
                    farmer=farmer,
                    field=field,
                    village=farmer.village or villages[0],
                    crop=crop,
                    problem_category=random.choice(categories),
                    crop_condition=random.choice(conditions),
                    notes=f"Routine visit to {farmer.name}'s farm. Crop: {crop.name}. "
                    f"Condition: {conditions[v_idx % len(conditions)]}.",
                    visit_date=visit_date,
                    latitude=Decimal(f"{11.6 + random.uniform(0, 0.5):.6f}"),
                    longitude=Decimal(f"{78.1 + random.uniform(0, 0.5):.6f}"),
                    status=random.choice(["pending", "verified"]),
                )
                visits.append(v)
        self.stdout.write(f"  Created {len(visits)} visits")
        return visits

    # ── STEP 8: Crop issues ──────────────────────────────

    def _create_issues(self, visits, crops, categories):
        severities = ["low", "medium", "high", "critical"]
        statuses = ["open", "open", "under_review", "resolved"]
        descriptions = [
            "Yellow leaf curl observed on lower canopy",
            "Brown spot disease spreading on leaves",
            "Stem borer damage detected near base",
            "Aphid infestation on new growth tips",
            "Nitrogen deficiency symptoms visible",
            "Root rot due to waterlogging",
            "White fly attack on underside of leaves",
            "Powdery mildew on leaf surface",
        ]

        issues = []
        for visit in visits:
            if random.random() < 0.7:
                issue = CropIssue.objects.create(
                    visit=visit,
                    crop=visit.crop,
                    problem_category=random.choice(categories),
                    severity=random.choice(severities),
                    status=random.choice(statuses),
                    description=random.choice(descriptions),
                )
                issues.append(issue)
        self.stdout.write(f"  Created {len(issues)} crop issues")
        return issues

    # ── STEP 9: Recommendations ──────────────────────────

    def _create_recommendations(self, issues, employees):
        fertilizers = [
            "Urea 46-0-0",
            "DAP 18-46-0",
            "MOP 0-0-60",
            "NPK 17-17-17",
            "Zinc Sulphate",
            "Neem Cake",
        ]
        pesticides = [
            "Chlorpyrifos 20 EC",
            "Imidacloprid 17.8 SL",
            "Mancozeb 75 WP",
            "Carbendazim 50 WP",
            "Neem Oil 1500 ppm",
            "Trichoderma viride",
        ]
        dosages = [
            "2 ml/L water",
            "1.5 g/L water",
            "25 kg/acre",
            "50 kg/acre",
            "3 ml/L water",
            "500 g/acre",
        ]
        notes_list = [
            "Apply in early morning or late evening for best results",
            "Repeat application after 10 days if symptoms persist",
            "Ensure uniform coverage on both sides of leaves",
            "Mix with sticker for better adhesion",
            "Apply during cool weather to prevent phytotoxicity",
            "Combine with organic matter for long-term soil health",
        ]

        admin_user = User.objects.filter(is_staff=True).first()
        given_by = admin_user or employees[0]

        count = 0
        for issue in issues:
            Recommendation.objects.create(
                issue=issue,
                given_by=given_by,
                fertilizer=random.choice(fertilizers),
                pesticide=random.choice(pesticides),
                dosage=random.choice(dosages),
                notes=random.choice(notes_list),
            )
            count += 1
        self.stdout.write(f"  Created {count} recommendations")

    # ── STEP 10: Visit media ─────────────────────────────

    def _create_visit_media(self, visits):
        count = 0
        for visit in visits:
            if random.random() < 0.5:
                # Create a tiny placeholder file instead of a real image
                placeholder = ContentFile(
                    b"placeholder",
                    name=f"visit_{visit.pk}_crop.jpg",
                )
                VisitMedia.objects.create(
                    visit=visit,
                    file=placeholder,
                    media_type="image",
                )
                count += 1
        self.stdout.write(f"  Created {count} visit media files")
