"""Visit media architecture: images, audio, video (60s), idempotency, reflection."""

from __future__ import annotations

import io
import struct
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from mobile_api.test_helpers import login_mobile_client
from visits.media_response import build_absolute_media_url, serialize_visit_media
from visits.media_validation import (
    CODE_UNSUPPORTED_MEDIA_TYPE,
    CODE_VIDEO_DURATION_EXCEEDED,
    MediaValidationError,
    probe_isobmff_duration_seconds,
    sanitize_original_filename,
    validate_visit_media_file_detailed,
)
from visits.models import Visit, VisitMedia
from visits.services.field_visit_service import submit_field_visit


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _box(box_type: bytes, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return struct.pack(">I", size) + box_type + payload


def _mp4_with_duration(seconds: float, timescale: int = 1000) -> bytes:
    """Minimal ISO BMFF with moov/trak/mdia/mdhd duration for tests."""
    duration = int(seconds * timescale)
    # mdhd v0: version/flags(4) + ctime(4) + mtime(4) + timescale(4) + duration(4) + lang/pre(4)
    mdhd_payload = (
        b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration)
        + b"\x55\xc4\x00\x00"
    )
    mdhd = _box(b"mdhd", mdhd_payload)
    mdia = _box(b"mdia", mdhd)
    trak = _box(b"trak", mdia)
    moov = _box(b"moov", trak)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    return ftyp + moov


class VisitMediaArchitectureTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="media_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-MEDIA",
            phone="9000000999",
            is_active_employee=True,
        )
        self.other = User.objects.create_user(username="media_other", password="x")
        EmployeeProfile.objects.create(
            user=self.other,
            employee_id="EMP-MEDIA-O",
            phone="9000000998",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="media_admin", password="x", is_staff=True, is_superuser=True
        )
        self.district = District.objects.create(name="Media District")
        self.village = Village.objects.create(
            name="Media Village", district=self.district
        )
        self.farmer = Farmer.objects.create(
            name="Media Farmer",
            phone="9888111222",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(
            name_en="Cotton", name_ta="Cotton", is_active=True
        )
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_media",
            defaults={"name": "Pest Media", "requires_problem_master": True},
        )
        self.problem = ProblemMaster.objects.create(
            name="Aphids", category=self.category, is_active=True
        )
        self.client = login_mobile_client(employee_id="EMP-MEDIA")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _payload(self, **extra):
        data = {
            "farmer_id": self.farmer.id,
            "crop_id": self.crop.id,
            "problem_category_id": self.category.id,
            "problem_master_id": self.problem.id,
            "problem_description": "Leaf damage",
            "recommendation": "Spray neem",
            "latitude": 12.97,
            "longitude": 77.59,
        }
        data.update(extra)
        return data

    def test_image_upload_appears_in_mobile_and_admin_detail(self):
        png = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
        r = self.client.post(
            "/api/v1/mobile/visits/",
            {**self._payload(local_sync_id="img-1"), "media": png},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.content)
        visit_id = r.data["data"]["visit_id"]
        media = r.data["data"]["visit"]["media_files"]
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["media_type"], "image")
        self.assertTrue(media[0]["url"] or media[0]["file_url"])
        self.assertNotIn("localhost:0", media[0]["url"] or "")

        detail = self.client.get(f"/api/v1/mobile/visits/{visit_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["data"]["media_files"]), 1)

        admin = self.admin_client.get(f"/api/v1/admin/visits/{visit_id}/")
        self.assertEqual(admin.status_code, 200)
        body = admin.data.get("data") or admin.data
        self.assertGreaterEqual(len(body.get("media_files") or []), 1)
        self.assertIn("images", body.get("media") or {})
        self.assertEqual(len(body["media"]["images"]), 1)

    def test_file_field_name_on_create_is_accepted(self):
        png = SimpleUploadedFile("a.png", _png_bytes(), content_type="image/png")
        r = self.client.post(
            "/api/v1/mobile/visits/",
            {**self._payload(local_sync_id="img-file"), "file": png},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data["data"]["visit"]["media_files"]), 1)

    def test_offline_replay_attaches_media_without_duplicating_visit(self):
        r1 = self.client.post(
            "/api/v1/mobile/visits/",
            self._payload(local_sync_id="replay-media"),
            format="multipart",
        )
        self.assertEqual(r1.status_code, 200)
        visit_id = r1.data["data"]["visit_id"]
        self.assertEqual(Visit.objects.filter(local_sync_id="replay-media").count(), 1)
        self.assertEqual(VisitMedia.objects.filter(visit_id=visit_id).count(), 0)

        png = SimpleUploadedFile("late.png", _png_bytes(), content_type="image/png")
        r2 = self.client.post(
            "/api/v1/mobile/visits/",
            {
                **self._payload(local_sync_id="replay-media"),
                "media": png,
                "client_upload_ids": "late-1",
            },
            format="multipart",
        )
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertTrue(r2.data["data"]["duplicate"])
        self.assertEqual(Visit.objects.filter(local_sync_id="replay-media").count(), 1)
        self.assertEqual(VisitMedia.objects.filter(visit_id=visit_id).count(), 1)
        self.assertEqual(len(r2.data["data"]["visit"]["media_files"]), 1)

    def test_audio_upload_returns_metadata(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="aud-v")
        ).visit
        # Audio can omit probeable duration.
        audio = SimpleUploadedFile(
            "note.m4a", b"not-a-real-m4a-but-ext-ok", content_type="audio/mp4"
        )
        with patch(
            "visits.media_validation.probe_media_duration_seconds", return_value=12.5
        ):
            r = self.client.post(
                f"/api/v1/mobile/visits/{visit.id}/media/",
                {
                    "file": audio,
                    "media_type": "audio",
                    "client_upload_id": "aud-1",
                    "duration_seconds": "12.5",
                },
                format="multipart",
            )
        self.assertIn(r.status_code, (200, 201), r.content)
        data = r.data["data"]
        self.assertEqual(data["media_type"], "audio")
        self.assertEqual(data["mime_type"], "audio/mp4")
        self.assertEqual(data["original_filename"], "note.m4a")
        self.assertAlmostEqual(float(data["duration_seconds"]), 12.5)

    def test_video_under_60_succeeds(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="vid-ok")
        ).visit
        blob = _mp4_with_duration(45.0)
        video = SimpleUploadedFile("clip.mp4", blob, content_type="video/mp4")
        r = self.client.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": video, "media_type": "video", "client_upload_id": "vid-1"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["data"]["media_type"], "video")
        self.assertLessEqual(float(r.data["data"]["duration_seconds"]), 60)

    def test_video_over_60_rejected(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="vid-long")
        ).visit
        blob = _mp4_with_duration(75.0)
        video = SimpleUploadedFile("long.mp4", blob, content_type="video/mp4")
        r = self.client.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": video, "media_type": "video", "client_upload_id": "vid-long"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.data.get("code"), CODE_VIDEO_DURATION_EXCEEDED)
        self.assertIn("60 seconds", r.data.get("message", ""))

    def test_unsupported_mime_rejected(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="bad-mime")
        ).visit
        f = SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload")
        r = self.client.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": f, "media_type": "image"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data.get("code"), CODE_UNSUPPORTED_MEDIA_TYPE)

    @override_settings(VISIT_MEDIA_IMAGE_MAX_BYTES=100)
    def test_oversized_image_rejected(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="big-img")
        ).visit
        big = SimpleUploadedFile(
            "big.png", _png_bytes() + b"0" * 200, content_type="image/png"
        )
        r = self.client.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": big, "media_type": "image"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data.get("code"), "IMAGE_TOO_LARGE")

    def test_duplicate_client_upload_id_idempotent(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="idem-m")
        ).visit
        png1 = SimpleUploadedFile("a.png", _png_bytes(), content_type="image/png")
        png2 = SimpleUploadedFile("b.png", _png_bytes(), content_type="image/png")
        r1 = self.client.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": png1, "media_type": "image", "client_upload_id": "same"},
            format="multipart",
        )
        r2 = self.client.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": png2, "media_type": "image", "client_upload_id": "same"},
            format="multipart",
        )
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            VisitMedia.objects.filter(visit=visit, client_upload_id="same").count(), 1
        )

    def test_wrong_owner_cannot_upload(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="own-m")
        ).visit
        other = login_mobile_client(employee_id="EMP-MEDIA-O")
        png = SimpleUploadedFile("x.png", _png_bytes(), content_type="image/png")
        r = other.post(
            f"/api/v1/mobile/visits/{visit.id}/media/",
            {"file": png, "media_type": "image"},
            format="multipart",
        )
        self.assertIn(r.status_code, (403, 404))

    def test_path_traversal_filename_sanitized(self):
        self.assertEqual(
            sanitize_original_filename("../../etc/passwd.png"), "passwd.png"
        )
        self.assertNotIn("..", sanitize_original_filename("../x.png"))

    def test_probe_mp4_duration(self):
        buf = io.BytesIO(_mp4_with_duration(30.0))
        dur = probe_isobmff_duration_seconds(buf)
        self.assertIsNotNone(dur)
        self.assertAlmostEqual(dur, 30.0, places=1)

    def test_missing_file_url_safe_fallback(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="miss-f")
        ).visit
        media = VisitMedia.objects.create(
            visit=visit,
            media_type="image",
            mime_type="image/png",
            original_filename="gone.png",
        )
        self.assertIsNone(build_absolute_media_url(media, request=None))
        payload = serialize_visit_media(media, request=None)
        self.assertIsNone(payload["url"])

    def test_visit_survives_failed_media_on_separate_upload(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="surv-m")
        ).visit
        vid = visit.id
        bad = SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")
        r = self.client.post(
            f"/api/v1/mobile/visits/{vid}/media/",
            {"file": bad, "media_type": "image"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Visit.objects.filter(pk=vid).exists())
        self.assertEqual(VisitMedia.objects.filter(visit_id=vid).count(), 0)

    def test_admin_serializer_includes_audio_video(self):
        visit = submit_field_visit(
            employee=self.employee, raw_data=self._payload(local_sync_id="av-admin")
        ).visit
        VisitMedia.objects.create(
            visit=visit,
            media_type="image",
            file=SimpleUploadedFile("i.png", _png_bytes(), content_type="image/png"),
            mime_type="image/png",
            original_filename="i.png",
        )
        with patch(
            "visits.media_validation.probe_media_duration_seconds", return_value=10.0
        ):
            validate_visit_media_file_detailed(
                file_obj=SimpleUploadedFile(
                    "a.m4a", b"x", content_type="audio/mp4"
                ),
                media_type="audio",
                client_duration_seconds=10,
            )
        VisitMedia.objects.create(
            visit=visit,
            media_type="audio",
            file=SimpleUploadedFile("a.m4a", b"x", content_type="audio/mp4"),
            mime_type="audio/mp4",
            original_filename="a.m4a",
            duration_seconds=10,
        )
        VisitMedia.objects.create(
            visit=visit,
            media_type="video",
            file=SimpleUploadedFile(
                "v.mp4", _mp4_with_duration(20), content_type="video/mp4"
            ),
            mime_type="video/mp4",
            original_filename="v.mp4",
            duration_seconds=20,
        )
        r = self.admin_client.get(f"/api/v1/admin/visits/{visit.id}/")
        self.assertEqual(r.status_code, 200)
        body = r.data.get("data") or r.data
        self.assertEqual(len(body["media_files"]), 3)
        self.assertEqual(len(body["media"]["images"]), 1)
        self.assertEqual(len(body["media"]["audio"]), 1)
        self.assertEqual(len(body["media"]["videos"]), 1)

    def test_video_duration_unknown_without_probe_rejected(self):
        with self.assertRaises(MediaValidationError) as ctx:
            validate_visit_media_file_detailed(
                file_obj=SimpleUploadedFile(
                    "x.mp4", b"not-mp4", content_type="video/mp4"
                ),
                media_type="video",
            )
        self.assertEqual(ctx.exception.code, "VIDEO_DURATION_UNKNOWN")
