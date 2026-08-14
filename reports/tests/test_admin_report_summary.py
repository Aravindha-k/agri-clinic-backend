"""Admin report summary aggregates."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit, VisitMedia
from django.core.files.uploadedfile import SimpleUploadedFile


class AdminReportSummaryTests(APITestCase):
    url = "/api/v1/reports/summary/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_report_sum",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.emp_a = User.objects.create_user(username="rep_a", password="x", first_name="Ann")
        self.emp_b = User.objects.create_user(username="rep_b", password="x", first_name="Bob")
        EmployeeProfile.objects.create(
            user=self.emp_a, employee_id="REP-A", phone="9000000001", is_active_employee=True
        )
        EmployeeProfile.objects.create(
            user=self.emp_b, employee_id="REP-B", phone="9000000002", is_active_employee=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        self.d1 = District.objects.create(name="Rep District 1")
        self.d2 = District.objects.create(name="Rep District 2")
        v1 = Village.objects.create(name="Rep Village 1", district=self.d1)
        v2 = Village.objects.create(name="Rep Village 2", district=self.d2)
        self.farmer1 = Farmer.objects.create(
            name="F1", phone="9333000001", district=self.d1, village=v1
        )
        self.farmer2 = Farmer.objects.create(
            name="F2", phone="9333000002", district=self.d2, village=v2
        )
        self.crop_rice = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.crop_millet = Crop.objects.create(
            name_en="Millet", name_ta="Millet", is_active=True
        )
        self.today = timezone.localdate()
        self.old = self.today - timedelta(days=10)

        self.v1 = self._visit(self.emp_a, self.farmer1, self.d1, v1, self.crop_rice, self.today)
        self.v2 = self._visit(self.emp_a, self.farmer1, self.d1, v1, self.crop_rice, self.today)
        self.v3 = self._visit(self.emp_b, self.farmer2, self.d2, v2, self.crop_millet, self.today)
        self.v_old = self._visit(self.emp_b, self.farmer2, self.d2, v2, self.crop_millet, self.old)

        VisitMedia.objects.create(
            visit=self.v1,
            uploaded_by=self.emp_a,
            media_type="image",
            mime_type="image/png",
            file=SimpleUploadedFile("x.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
            original_filename="x.png",
        )

    def _visit(self, emp, farmer, district, village, crop, visit_date, **extra):
        return Visit.objects.create(
            employee=emp,
            farmer=farmer,
            farmer_name=farmer.name,
            crop=crop,
            latitude=11.0,
            longitude=78.0,
            district=district,
            village=village,
            visit_date=visit_date,
            **extra,
        )

    def test_unauthenticated_blocked(self):
        c = APIClient()
        r = c.get(self.url)
        self.assertIn(r.status_code, (401, 403))

    def test_summary_totals_match_filtered_set(self):
        r = self.client.get(
            self.url,
            {"from": self.today.isoformat(), "to": self.today.isoformat()},
        )
        self.assertEqual(r.status_code, 200)
        data = r.data["data"]
        self.assertEqual(data["totals"]["visits"], 3)
        self.assertEqual(data["totals"]["submitted_visits"], 3)
        self.assertEqual(data["totals"]["employees"], 2)
        self.assertEqual(data["totals"]["farmers"], 2)
        self.assertEqual(data["totals"]["gps_compliant"], 3)
        self.assertEqual(data["totals"]["visits_with_evidence"], 1)
        self.assertEqual(sum(x["count"] for x in data["visits_by_employee"]), 3)
        self.assertEqual(sum(x["count"] for x in data["visits_by_crop"]), 3)
        self.assertEqual(sum(x["count"] for x in data["visits_by_day"]), 3)

    def test_employee_filter(self):
        r = self.client.get(
            self.url,
            {
                "from": self.today.isoformat(),
                "to": self.today.isoformat(),
                "employee": "REP-A",
            },
        )
        self.assertEqual(r.status_code, 200)
        data = r.data["data"]
        self.assertEqual(data["totals"]["visits"], 2)
        self.assertEqual(len(data["visits_by_employee"]), 1)
        self.assertEqual(data["visits_by_employee"][0]["employee_code"], "REP-A")

    def test_district_filter(self):
        r = self.client.get(
            self.url,
            {
                "from": self.today.isoformat(),
                "to": self.today.isoformat(),
                "district": self.d2.id,
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["data"]["totals"]["visits"], 1)

    def test_invalid_date(self):
        r = self.client.get(self.url, {"from": "not-a-date"})
        self.assertEqual(r.status_code, 400)
