from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit
from visits.submitted import SUBMIT_VISIT_REQUIRED_MESSAGE


class MobileAPIAuditTest(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="mob_audit", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-AUDIT",
            phone="9000000888",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="admin_audit", password="x", is_staff=True, is_superuser=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.employee)

        district = District.objects.create(name="Audit D")
        village = Village.objects.create(name="Audit V", district=district)
        self.farmer = Farmer.objects.create(
            name="Audit Farmer",
            phone="9777666555",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.payload = {
            "farmer": self.farmer.id,
            "crop": self.crop.id,
            "latitude": 12.97,
            "longitude": 77.59,
        }

    def test_incomplete_submit_no_db_row(self):
        before = Visit.objects.count()
        r = self.client.post("/api/v1/mobile/visits/", {"farmer": self.farmer.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["message"], SUBMIT_VISIT_REQUIRED_MESSAGE)
        self.assertEqual(Visit.objects.count(), before)

    def test_local_sync_id_idempotent(self):
        body = {**self.payload, "local_sync_id": "offline-uuid-1"}
        r1 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r1.status_code, 200)
        vid = r1.data["data"]["visit_id"]
        r2 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["data"]["duplicate"])
        self.assertEqual(r2.data["data"]["visit_id"], vid)
        self.assertEqual(
            Visit.objects.filter(employee=self.employee, local_sync_id="offline-uuid-1").count(),
            1,
        )

    def test_dashboard_no_active_visit(self):
        r = self.client.get("/api/v1/mobile/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["data"]["active_visit"])
        self.assertEqual(r.data["data"]["pending_visits"], 0)

    def test_visit_detail_and_map(self):
        create = self.client.post("/api/v1/mobile/visits/", self.payload, format="json")
        vid = create.data["data"]["visit_id"]
        detail = self.client.get(f"/api/v1/mobile/visits/{vid}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["id"], vid)
        self.assertIn("timeline", detail.data["data"])

        mp = self.client.get("/api/v1/mobile/map/visits/")
        self.assertEqual(mp.status_code, 200)
        self.assertGreaterEqual(len(mp.data["data"]["markers"]), 1)

    def test_farmer_detail_mobile_route(self):
        r = self.client.get(f"/api/v1/mobile/farmers/{self.farmer.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["data"]["id"], self.farmer.id)

    def test_admin_dashboard_unaffected(self):
        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        r = admin_client.get("/api/v1/admin/dashboard/stats/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("visits", r.data["data"])
