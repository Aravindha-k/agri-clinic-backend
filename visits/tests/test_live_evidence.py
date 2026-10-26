"""Server-side live-evidence enforcement for employee visit photos."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from mobile_api.test_helpers import assign_operational_territory, login_mobile_client
from visits.models import Visit, VisitMedia


def _now_iso():
    return timezone.now().isoformat()


def _meta(lat=10.79, lng=78.70, acc=20, when=None, source="camera"):
    return {
        "capture_source": source,
        "capture_latitude": lat,
        "capture_longitude": lng,
        "capture_accuracy_m": acc,
        "captured_at": (when or _now_iso()),
    }


class LiveEvidenceEnforcementTest(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="emp_ev", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-EV-01",
            phone="9000000111",
            is_active_employee=True,
        )
        district = District.objects.create(name="EV District")
        self.village = Village.objects.create(name="EV Village", district=district)
        assign_operational_territory(self.employee, self.village)
        self.farmer = Farmer.objects.create(
            name="EV Farmer",
            phone="9888777002",
            district=district,
            village=self.village,
            gps_location="10.79,78.70",
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.category_pest, _ = ProblemCategory.objects.get_or_create(
            code="pest",
            defaults={"name": "Pest", "requires_problem_master": True},
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category_pest, name="Stem borer", crop=self.crop
        )
        self.client = login_mobile_client(employee_id="EMP-EV-01")
        payload = {
            "farmer_name": "EV Farmer",
            "phone_number": "9888777002",
            "village_id": self.village.id,
            "crop_id": self.crop.id,
            "acreage": 2.0,
            "problem_category_id": self.category_pest.id,
            "problem_master_id": self.problem.id,
            "problem_description": "Damage seen.",
        }
        r = self.client.post("/api/v1/mobile/visits/", payload, format="json")
        assert r.status_code in (200, 201), r.data
        self.visit = Visit.objects.get(pk=r.data["data"]["visit_id"])

    def _image(self, name="proof.jpg", size=1024):
        return SimpleUploadedFile(name, b"x" * size, content_type="image/jpeg")

    def _upload(self, fields):
        return self.client.post(
            f"/api/v1/mobile/visits/{self.visit.id}/media/", fields, format="multipart"
        )

    def test_new_employee_visit_starts_evidence_pending(self):
        self.assertEqual(self.visit.evidence_status, "pending")

    def test_image_without_capture_meta_rejected(self):
        r = self._upload({"file": self._image(), "media_type": "image"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.visit.media_files.count(), 0)

    def test_gallery_source_image_rejected(self):
        r = self._upload(
            {
                "file": self._image(),
                "media_type": "image",
                **_meta(source="gallery"),
            }
        )
        self.assertEqual(r.status_code, 400)

    def test_image_without_gps_rejected(self):
        meta = _meta()
        del meta["capture_latitude"]
        del meta["capture_longitude"]
        r = self._upload({"file": self._image(), "media_type": "image", **meta})
        self.assertEqual(r.status_code, 400)

    def test_poor_accuracy_rejected(self):
        r = self._upload(
            {"file": self._image(), "media_type": "image", **_meta(acc=9999)}
        )
        self.assertEqual(r.status_code, 400)

    def test_future_capture_time_rejected(self):
        future = (timezone.now() + timedelta(hours=2)).isoformat()
        r = self._upload(
            {"file": self._image(), "media_type": "image", **_meta(when=future)}
        )
        self.assertEqual(r.status_code, 400)

    def test_old_capture_time_rejected(self):
        old = (timezone.now() - timedelta(days=3)).isoformat()
        r = self._upload(
            {"file": self._image(), "media_type": "image", **_meta(when=old)}
        )
        self.assertEqual(r.status_code, 400)

    def test_far_capture_location_rejected(self):
        r = self._upload(
            {
                "file": self._image(),
                "media_type": "image",
                **_meta(lat=20.0, lng=80.0),
            }
        )
        self.assertEqual(r.status_code, 400)

    def test_valid_camera_image_accepted_and_marks_verified(self):
        r = self._upload({"file": self._image(), "media_type": "image", **_meta()})
        self.assertIn(r.status_code, (200, 201), r.data)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.evidence_status, "verified")
        media = self.visit.media_files.get()
        self.assertEqual(media.capture_source, "camera")
        self.assertEqual(media.capture_latitude, 10.79)
        self.assertTrue(media.file_hash)

    def test_same_file_reused_on_other_visit_rejected(self):
        blob = b"shared-bytes" * 64
        r1 = self._upload(
            {
                "file": SimpleUploadedFile("a.jpg", blob, content_type="image/jpeg"),
                "media_type": "image",
                **_meta(),
            }
        )
        self.assertIn(r1.status_code, (200, 201), r1.data)
        other = Visit.objects.create(
            employee=self.employee, farmer=self.farmer, crop=self.crop,
            village=self.village, problem_category=self.category_pest,
            problem_master=self.problem, land_area=1.0,
            problem_description="x", evidence_status="pending",
        )
        r2 = self.client.post(
            f"/api/v1/mobile/visits/{other.id}/media/",
            {
                "file": SimpleUploadedFile("b.jpg", blob, content_type="image/jpeg"),
                "media_type": "image",
                **_meta(),
            },
            format="multipart",
        )
        self.assertEqual(r2.status_code, 400)

    def test_audio_upload_not_subject_to_camera_rule(self):
        audio = SimpleUploadedFile("note.m4a", b"y" * 256, content_type="audio/m4a")
        r = self._upload({"file": audio, "media_type": "audio"})
        self.assertIn(r.status_code, (200, 201), r.data)

    def test_inline_media_without_meta_fails_create(self):
        before = Visit.objects.count()
        r = self.client.post(
            "/api/v1/mobile/visits/",
            {
                "farmer_name": "EV Farmer",
                "phone_number": "9888777002",
                "village_id": self.village.id,
                "crop_id": self.crop.id,
                "acreage": 2.0,
                "problem_category_id": self.category_pest.id,
                "problem_master_id": self.problem.id,
                "problem_description": "Damage seen.",
                "media": [self._image()],
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Visit.objects.count(), before, "failed attach must roll back the visit")

    def test_no_trusted_field_gps_still_accepts(self):
        self.farmer.gps_location = ""
        self.farmer.save(update_fields=["gps_location"])
        r = self._upload(
            {"file": self._image(), "media_type": "image", **_meta(lat=11.0, lng=79.0)}
        )
        self.assertIn(r.status_code, (200, 201), r.data)
