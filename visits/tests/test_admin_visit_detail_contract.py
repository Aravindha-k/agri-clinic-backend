"""Admin visit detail location + unified evidence contract."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Taluk, Village
from visits.models import Visit, VisitMedia


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


class AdminVisitDetailContractTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="detail_admin", password="x", is_staff=True, is_superuser=True
        )
        self.employee = User.objects.create_user(username="detail_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-DTL",
            phone="9000000501",
            is_active_employee=True,
        )
        self.district = District.objects.create(name="Trichy")
        self.taluk = Taluk.objects.create(name="Lalgudi", district=self.district)
        self.village = Village.objects.create(
            name="Kedar",
            district=self.district,
            taluk=self.taluk,
        )
        self.farmer = Farmer.objects.create(
            name="Test user",
            phone="9888111222",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Bhendi", name_ta="வெண்டை", is_active=True)
        self.visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            district=self.district,
            village=self.village,
            crop=self.crop,
            farmer_name=self.farmer.name,
            latitude=10.79,
            longitude=78.70,
        )
        VisitMedia.objects.create(
            visit=self.visit,
            file=SimpleUploadedFile("field.jpg", _png_bytes(), content_type="image/jpeg"),
            media_type="image",
            mime_type="image/jpeg",
            original_filename="field.jpg",
            uploaded_by=self.employee,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_detail_returns_location_names_not_only_pks(self):
        resp = self.client.get(f"/api/v1/admin/visits/{self.visit.id}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["district"], self.district.id)
        self.assertEqual(data["district_name"], "Trichy")
        self.assertEqual(data["taluk_name"], "Lalgudi")
        self.assertEqual(data["village_name"], "Kedar")
        self.assertNotEqual(data["district_name"], str(self.district.id))

    def test_taluk_from_village_when_farmer_taluk_missing(self):
        Farmer.objects.filter(pk=self.farmer.pk).update(taluk=None)
        resp = self.client.get(f"/api/v1/admin/visits/{self.visit.id}/")
        data = resp.json()
        self.assertEqual(data["taluk_name"], "Lalgudi")

    def test_unified_evidence_on_detail_matches_count(self):
        resp = self.client.get(f"/api/v1/admin/visits/{self.visit.id}/")
        data = resp.json()
        self.assertEqual(data["evidence_count"], 1)
        self.assertEqual(len(data["evidence"]), 1)
        row = data["evidence"][0]
        self.assertTrue(row.get("evidence_key", "").startswith("visit_media:"))
        self.assertTrue(row.get("file_url"))

    def test_attachments_endpoint_matches_detail_evidence(self):
        detail = self.client.get(f"/api/v1/admin/visits/{self.visit.id}/").json()
        listed = self.client.get(
            f"/api/v1/admin/visits/{self.visit.id}/attachments/"
        ).json()["data"]
        self.assertEqual(detail["evidence_count"], len(listed))
        self.assertEqual(
            detail["evidence"][0]["evidence_key"],
            listed[0]["evidence_key"],
        )
