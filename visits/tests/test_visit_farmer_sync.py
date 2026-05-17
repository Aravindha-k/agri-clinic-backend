from django.contrib.auth.models import User
from django.test import TestCase

from masters.models import Crop, District, Farmer, Village
from visits.models import Visit
from visits.visit_response import build_visit_farmer_block, crop_display_name


class VisitFarmerBlockTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="emp1", password="x")
        district = District.objects.create(name="D1")
        village = Village.objects.create(name="V1", district=district)
        self.village = village
        self.farmer = Farmer.objects.create(
            name="Ravi",
            phone="9000000001",
            district=district,
            village=village,
            created_by_employee=self.user,
            assigned_employee=self.user,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)

    def test_build_visit_farmer_block_from_fk(self):
        visit = Visit.objects.create(
            employee=self.user,
            farmer=self.farmer,
            crop=self.crop,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=self.village,
            latitude=12.5,
            longitude=78.5,
            status="pending",
        )
        block = build_visit_farmer_block(visit)
        self.assertEqual(block["id"], self.farmer.id)
        self.assertEqual(block["name"], "Ravi")
        self.assertEqual(block["mobile"], "9000000001")
        self.assertEqual(block["village"], "V1")
        self.assertIn("Rice", crop_display_name(visit))
