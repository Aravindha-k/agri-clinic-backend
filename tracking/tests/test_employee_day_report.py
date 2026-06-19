from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from tracking.models import DutySession, EmployeeRoutePoint
from tracking.route_point_filter import MIN_ROUTE_INTERVAL_SECONDS
from visits.models import Visit


class EmployeeDayReportAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="er_admin",
            password="x",
            is_staff=True,
        )
        self.employee = User.objects.create_user(username="er_emp", password="secret123")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="ER-001",
            phone="9000000555",
            is_active_employee=True,
        )
        self.district = District.objects.create(name="ER District")
        self.village = Village.objects.create(name="ER Village", district=self.district)
        self.farmer = Farmer.objects.create(
            name="ER Farmer",
            phone="9444444444",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Wheat", name_ta="Wheat", is_active=True)
        self.today = timezone.localdate()

        self.client = APIClient()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self._auth_employee()

    def _auth_employee(self):
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "ER-001",
                "password": "secret123",
                "device_name": "Test Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )

    def _start_duty_and_route(self):
        self.client.post(
            "/api/tracking/duty/start/",
            {"latitude": 12.9716, "longitude": 77.5946},
            format="json",
        )
        t0 = timezone.now()
        self.client.post(
            "/api/tracking/location/update/",
            {
                "latitude": 12.9716,
                "longitude": 77.5946,
                "captured_at": t0.isoformat(),
            },
            format="json",
        )
        self.client.post(
            "/api/tracking/location/update/",
            {
                "latitude": 12.9750,
                "longitude": 77.5980,
                "captured_at": (t0 + timedelta(seconds=MIN_ROUTE_INTERVAL_SECONDS + 5)).isoformat(),
            },
            format="json",
        )

    def _create_visit(self, *, local_sync_id=None):
        return Visit.objects.create(
            employee=self.employee,
            visit_date=self.today,
            visit_time=timezone.now().time(),
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=self.village,
            crop=self.crop,
            latitude=12.9800,
            longitude=77.6000,
            local_sync_id=local_sync_id,
        )

    def test_admin_visits_by_date(self):
        self._start_duty_and_route()
        visit = self._create_visit(local_sync_id="offline-visit-1")
        duty = DutySession.objects.get(user=self.employee, is_active=True)
        visit.refresh_from_db()

        url = f"/api/admin/visits/employee/{self.profile.pk}/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["completed_visits"], 1)
        self.assertEqual(data["total_visits"], 1)
        self.assertEqual(len(data["visits"]), 1)
        self.assertTrue(data["visits"][0]["is_offline_sync"])
        self.assertEqual(data["visits"][0]["duty_session_id"], duty.id)
        visit_row = data["visits"][0]
        self.assertEqual(visit_row["crop_id"], self.crop.id)
        self.assertEqual(visit_row["crop_name"], "Wheat / Wheat")
        self.assertIsNone(visit_row["crop_variety"])

    def test_admin_day_report_visit_crop_fields(self):
        self._start_duty_and_route()
        visit = self._create_visit(local_sync_id="crop-test")
        visit.variety = "HD-2967"
        visit.crop_stage = "Flowering"
        visit.save(update_fields=["variety", "crop_stage"])

        day_report_url = f"/api/admin/employees/{self.profile.pk}/day-report/"
        r = self.admin_client.get(day_report_url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        visit_row = r.data["data"]["visits"]["visits"][0]
        self.assertEqual(visit_row["crop_id"], self.crop.id)
        self.assertEqual(visit_row["crop_name"], "Wheat / Wheat")
        self.assertEqual(visit_row["crop_variety"], "HD-2967")
        self.assertEqual(visit_row["crop_stage"], "Flowering")

        visits_url = f"/api/admin/visits/employee/{self.profile.pk}/"
        r2 = self.admin_client.get(visits_url, {"date": str(self.today)})
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        visit_row2 = r2.data["data"]["visits"][0]
        self.assertEqual(visit_row2["crop_id"], self.crop.id)
        self.assertEqual(visit_row2["crop_name"], "Wheat / Wheat")
        self.assertEqual(visit_row2["crop_variety"], "HD-2967")
        self.assertEqual(visit_row2["crop_stage"], "Flowering")

    def test_admin_day_summary(self):
        self._start_duty_and_route()
        self._create_visit()
        url = f"/api/admin/employees/{self.profile.pk}/day-summary/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["employee"]["employee_id"], "ER-001")
        self.assertGreaterEqual(data["route_point_count"], 1)
        self.assertEqual(data["visits_completed"], 1)
        self.assertIn("duty", data)

    def test_admin_day_report_full_payload(self):
        self._start_duty_and_route()
        self._create_visit(local_sync_id="sync-99")
        url = f"/api/admin/employees/{self.employee.id}/day-report/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertIn("employee", data)
        self.assertIn("duty", data)
        self.assertIn("route", data)
        self.assertIn("polyline", data["route"])
        self.assertIn("visits", data)
        self.assertEqual(data["summary"]["completed_visits"], 1)
        self.assertIn("live_location", data)
        self.assertIn("locations", data)
        self.assertIn("offline_sync", data)
        self.assertGreaterEqual(
            EmployeeRoutePoint.objects.filter(
                user=self.employee, point_type=EmployeeRoutePoint.POINT_VISIT
            ).count(),
            1,
        )

    def test_v1_admin_day_report_path(self):
        self._start_duty_and_route()
        url = f"/api/v1/tracking/admin/employees/{self.profile.pk}/day-report/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_pending_visit_in_report(self):
        Visit.objects.create(
            employee=self.employee,
            visit_date=self.today,
            farmer_name="Incomplete",
            status="pending",
        )
        url = f"/api/admin/employees/{self.profile.pk}/day-report/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data["data"]["visits"]["pending_visits"], 1)
