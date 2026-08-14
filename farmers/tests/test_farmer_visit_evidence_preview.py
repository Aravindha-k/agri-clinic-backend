"""Farmer visit list evidence preview contract."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import override_settings
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from visits.models import Visit, VisitAttachment, VisitMedia


@override_settings(MEDIA_URL="/media/")
class FarmerVisitEvidencePreviewTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_ev_preview",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.emp = User.objects.create_user(username="emp_ev", password="x")
        EmployeeProfile.objects.create(
            user=self.emp,
            employee_id="EMP-EV",
            phone="9000000888",
            is_active_employee=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        district = District.objects.create(name="Ev District")
        village = Village.objects.create(name="Ev Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Ev Farmer",
            phone="9222000222",
            district=district,
            village=village,
        )
        crop = Crop.objects.create(name_en="Cotton", name_ta="Cotton", is_active=True)
        self.visit = Visit.objects.create(
            employee=self.emp,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            crop=crop,
            latitude=10.1,
            longitude=78.2,
            district=district,
            village=village,
        )
        self.url = f"/api/v1/farmers/{self.farmer.id}/visits/"

    def _png(self, name="a.png"):
        # Minimal PNG header bytes are enough for FileField storage in tests.
        return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\nfake", content_type="image/png")

    def test_evidence_preview_and_count(self):
        m1 = VisitMedia.objects.create(
            visit=self.visit,
            uploaded_by=self.emp,
            media_type="image",
            mime_type="image/png",
            file=self._png("one.png"),
            original_filename="one.png",
        )
        m2 = VisitMedia.objects.create(
            visit=self.visit,
            uploaded_by=self.emp,
            media_type="image",
            mime_type="image/png",
            file=self._png("two.png"),
            original_filename="two.png",
        )
        VisitMedia.objects.create(
            visit=self.visit,
            uploaded_by=self.emp,
            media_type="audio",
            mime_type="audio/mpeg",
            file=SimpleUploadedFile("a.mp3", b"ID3", content_type="audio/mpeg"),
            original_filename="a.mp3",
        )
        VisitAttachment.objects.create(
            visit=self.visit,
            employee=self.emp,
            uploaded_by=self.emp,
            attachment_type="image",
            mime_type="image/jpeg",
            file=self._png("att.jpg"),
            original_filename="att.jpg",
        )

        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        rows = r.data["results"] if "results" in r.data else r.data.get("data", {}).get("results", r.data)
        if isinstance(r.data, dict) and "data" in r.data and isinstance(r.data["data"], dict):
            rows = r.data["data"].get("results", rows)
        self.assertTrue(rows)
        row = next(x for x in rows if x["id"] == self.visit.id)
        self.assertEqual(row["evidence_count"], 4)
        self.assertLessEqual(len(row["evidence_preview"]), 3)
        for item in row["evidence_preview"]:
            self.assertEqual(item["type"], "image")
            self.assertIn("evidence_key", item)
            self.assertTrue(item["file_url"])
            self.assertNotIn("\\", item["file_url"])
            self.assertFalse(item["file_url"].startswith("/home"))
        keys = {i["evidence_key"] for i in row["evidence_preview"]}
        self.assertIn(f"visit_media:{m1.id}", keys)
        self.assertTrue(keys)

    def test_no_duplicate_evidence_keys_in_preview(self):
        VisitMedia.objects.create(
            visit=self.visit,
            uploaded_by=self.emp,
            media_type="image",
            mime_type="image/png",
            file=self._png("dup.png"),
            original_filename="dup.png",
        )
        r = self.client.get(self.url)
        rows = r.data["results"]
        row = next(x for x in rows if x["id"] == self.visit.id)
        keys = [i["evidence_key"] for i in row["evidence_preview"]]
        self.assertEqual(len(keys), len(set(keys)))
