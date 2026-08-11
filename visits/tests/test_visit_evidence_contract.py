"""Unified Admin evidence READ: VisitMedia + VisitAttachment."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from mobile_api.test_helpers import login_mobile_client
from visits.models import Visit, VisitAttachment, VisitMedia


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


class VisitEvidenceContractTests(APITestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="ev_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-EV",
            phone="9000000401",
            is_active_employee=True,
        )
        self.other = User.objects.create_user(username="ev_other", password="x")
        EmployeeProfile.objects.create(
            user=self.other,
            employee_id="EMP-EV-O",
            phone="9000000402",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="ev_admin", password="x", is_staff=True, is_superuser=True
        )
        district = District.objects.create(name="Ev District")
        village = Village.objects.create(name="Ev Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Evidence Farmer",
            phone="9888000111",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.mobile = login_mobile_client(employee_id="EMP-EV")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=11.0,
            longitude=77.0,
            farmer_name=self.farmer.name,
        )
        self.other_visit = Visit.objects.create(
            employee=self.other,
            farmer=self.farmer,
            crop=self.crop,
            latitude=11.1,
            longitude=77.1,
            farmer_name=self.farmer.name,
        )

    def _admin_url(self, visit_id=None):
        return f"/api/v1/admin/visits/{visit_id or self.visit.id}/attachments/"

    def _add_media(
        self,
        visit=None,
        *,
        pk=None,
        name="shot.png",
        media_type="image",
        mime="image/png",
        content=None,
    ):
        visit = visit or self.visit
        media = VisitMedia(
            visit=visit,
            uploaded_by=self.employee,
            media_type=media_type,
            mime_type=mime,
            original_filename=name,
        )
        if pk is not None:
            media.id = pk
        media.file.save(name, ContentFile(content or _png_bytes()), save=True)
        return media

    def _add_attachment(
        self,
        visit=None,
        *,
        pk=None,
        name="proof.jpg",
        attachment_type="image",
        mime="image/jpeg",
        content=None,
    ):
        visit = visit or self.visit
        att = VisitAttachment(
            visit=visit,
            employee=self.employee,
            uploaded_by=self.employee,
            attachment_type=attachment_type,
            mime_type=mime,
            original_filename=name,
        )
        if pk is not None:
            att.id = pk
        att.file.save(name, ContentFile(content or b"x" * 64), save=True)
        return att

    def _assert_public_media_url(self, url):
        self.assertTrue(url, "file_url/url must be present")
        self.assertTrue(str(url).startswith("http"), url)
        self.assertIn("/media/", str(url))
        self.assertNotIn("/opt/", str(url))
        self.assertNotIn("/api/v1/media/", str(url))
        self.assertNotIn("127.0.0.1", str(url))
        self.assertNotIn("localhost", str(url))

    def test_a_visitmedia_only_appears_on_admin_attachments(self):
        media = self._add_media(name="visit-1786363163135.jpg", mime="image/jpeg")
        r = self.admin_client.get(self._admin_url())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["success"])
        rows = r.data["data"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source"], "visit_media")
        self.assertEqual(row["source_id"], media.id)
        self.assertEqual(row["evidence_key"], f"visit_media:{media.id}")
        self.assertEqual(row["attachment_type"], "image")
        self._assert_public_media_url(row["file_url"])
        self._assert_public_media_url(row["url"])
        self.assertIn("visit-1786363163135", row["file_url"])

    def test_b_visitattachment_only_still_appears(self):
        att = self._add_attachment()
        r = self.admin_client.get(self._admin_url())
        self.assertEqual(r.status_code, 200)
        rows = r.data["data"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source"], "visit_attachment")
        self.assertEqual(row["id"], att.id)
        self.assertEqual(row["source_id"], att.id)
        self.assertEqual(row["evidence_key"], f"visit_attachment:{att.id}")
        self.assertEqual(row["attachment_type"], "image")
        self._assert_public_media_url(row["file_url"])

    def test_c_both_sources_included(self):
        self._add_media()
        self._add_attachment()
        r = self.admin_client.get(self._admin_url())
        self.assertEqual(r.status_code, 200)
        rows = r.data["data"]
        self.assertEqual(len(rows), 2)
        sources = {row["source"] for row in rows}
        self.assertEqual(sources, {"visit_media", "visit_attachment"})

    def test_d_urls_resolve_to_media_prefix(self):
        self._add_media()
        self._add_attachment()
        r = self.admin_client.get(self._admin_url())
        for row in r.data["data"]:
            self._assert_public_media_url(row["file_url"])
            self._assert_public_media_url(row["url"])

    def test_e_same_numeric_id_no_identity_collision(self):
        media = self._add_media(pk=3, name="from-media.jpg")
        att = self._add_attachment(pk=3, name="from-att.jpg")
        self.assertEqual(media.id, 3)
        self.assertEqual(att.id, 3)
        r = self.admin_client.get(self._admin_url())
        rows = r.data["data"]
        self.assertEqual(len(rows), 2)
        keys = {row["evidence_key"] for row in rows}
        self.assertEqual(keys, {"visit_media:3", "visit_attachment:3"})
        ids = {row["id"] for row in rows}
        self.assertEqual(len(ids), 2)
        media_row = next(row for row in rows if row["source"] == "visit_media")
        att_row = next(row for row in rows if row["source"] == "visit_attachment")
        self.assertEqual(media_row["id"], "visit_media:3")
        self.assertEqual(att_row["id"], 3)
        self.assertEqual(media_row["source_id"], 3)
        self.assertEqual(att_row["source_id"], 3)

    def test_f_attachment_write_flow_unchanged(self):
        url = f"/api/v1/mobile/visits/{self.visit.id}/attachments/"
        r = self.mobile.post(
            url,
            {
                "attachment_type": "image",
                "file": SimpleUploadedFile(
                    "new-att.jpg", b"y" * 128, content_type="image/jpeg"
                ),
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["data"]["attachment_type"], "image")
        self.assertIsInstance(r.data["data"]["id"], int)
        self.assertTrue(VisitAttachment.objects.filter(pk=r.data["data"]["id"]).exists())

    def test_g_visitmedia_upload_unchanged(self):
        png = SimpleUploadedFile("a.png", _png_bytes(), content_type="image/png")
        r = self.mobile.post(
            f"/api/v1/mobile/visits/{self.visit.id}/media/",
            {"file": png, "media_type": "image", "client_upload_id": "ev-up-1"},
            format="multipart",
        )
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(VisitMedia.objects.filter(visit=self.visit).count(), 1)
        payload = r.data["data"]
        media_row = payload if payload.get("media_type") else None
        if media_row is None and isinstance(payload.get("media_files"), list):
            media_row = payload["media_files"][0]
        self.assertIsNotNone(media_row)
        self.assertEqual(media_row["media_type"], "image")

    def test_h_does_not_leak_other_visit_evidence(self):
        self._add_media(self.other_visit, name="other.png")
        self._add_attachment(self.other_visit, name="other.jpg")
        own = self._add_media(self.visit, name="mine.png")
        r = self.admin_client.get(self._admin_url(self.visit.id))
        rows = r.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_id"], own.id)
        self.assertEqual(rows[0]["evidence_key"], f"visit_media:{own.id}")

    def test_i_permissions_unchanged(self):
        self._add_media()
        anon = APIClient()
        r = anon.get(self._admin_url())
        self.assertIn(r.status_code, (401, 403))

        employee_client = APIClient()
        employee_client.force_authenticate(user=self.employee)
        r2 = employee_client.get(self._admin_url())
        self.assertEqual(r2.status_code, 403)

    def test_j_type_normalization_image_pdf_audio(self):
        self._add_media(name="leaf.jpg", media_type="image", mime="image/jpeg")
        VisitMedia.objects.create(
            visit=self.visit,
            uploaded_by=self.employee,
            media_type="audio",
            mime_type="audio/mp4",
            original_filename="note.m4a",
            file=ContentFile(b"audio-bytes", name="note.m4a"),
        )
        VisitAttachment.objects.create(
            visit=self.visit,
            employee=self.employee,
            uploaded_by=self.employee,
            attachment_type="pdf",
            mime_type="application/pdf",
            original_filename="lab.pdf",
            file=ContentFile(b"%PDF-1.4", name="lab.pdf"),
        )
        r = self.admin_client.get(self._admin_url())
        types = {row["attachment_type"] for row in r.data["data"]}
        self.assertEqual(types, {"image", "audio", "pdf"})

    def test_k_production_style_visitmedia_survives_without_reupload(self):
        media = VisitMedia(
            id=3,
            visit=self.visit,
            uploaded_by=self.employee,
            media_type="image",
            mime_type="image/jpeg",
            original_filename="visit-1786363163135.jpg",
        )
        media.file.save(
            "visit-1786363163135.jpg",
            ContentFile(b"\xff\xd8\xff" + b"0" * 200),
            save=True,
        )
        r = self.admin_client.get(self._admin_url())
        self.assertEqual(len(r.data["data"]), 1)
        row = r.data["data"][0]
        self.assertEqual(row["evidence_key"], "visit_media:3")
        self.assertEqual(row["source"], "visit_media")
        self.assertIn("visit-1786363163135", row["file_url"])
        self.assertIn("/media/visit_media/", row["file_url"])
        self.assertTrue(str(row["file_url"]).endswith(".jpg"))
        self.assertEqual(VisitMedia.objects.filter(pk=3).count(), 1)

    def test_delete_numeric_id_does_not_remove_visitmedia(self):
        media = self._add_media(pk=3)
        att = self._add_attachment(pk=3)
        d = self.mobile.delete(
            f"/api/v1/mobile/visits/{self.visit.id}/attachments/{att.id}/"
        )
        self.assertEqual(d.status_code, 200)
        self.assertFalse(VisitAttachment.objects.filter(pk=3).exists())
        self.assertTrue(VisitMedia.objects.filter(pk=media.id).exists())

        r = self.admin_client.get(self._admin_url())
        self.assertEqual(len(r.data["data"]), 1)
        self.assertEqual(r.data["data"][0]["source"], "visit_media")

    def test_mobile_attachments_list_stays_attachment_only(self):
        self._add_media()
        self._add_attachment()
        r = self.mobile.get(f"/api/v1/mobile/visits/{self.visit.id}/attachments/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["data"]), 1)
        self.assertEqual(r.data["data"][0]["attachment_type"], "image")
        self.assertNotIn("source", r.data["data"][0])

    def test_mobile_detail_still_exposes_media_files(self):
        self._add_media()
        r = self.mobile.get(f"/api/v1/mobile/visits/{self.visit.id}/")
        self.assertEqual(r.status_code, 200)
        body = r.data.get("data") or r.data
        self.assertGreaterEqual(len(body.get("media_files") or []), 1)

    def test_same_storage_path_deduped_once(self):
        media = self._add_media(name="shared.jpg")
        path = media.file.name
        att = VisitAttachment(
            visit=self.visit,
            employee=self.employee,
            uploaded_by=self.employee,
            attachment_type="image",
            mime_type="image/jpeg",
            original_filename="shared.jpg",
        )
        att.file.name = path
        att.save()
        r = self.admin_client.get(self._admin_url())
        self.assertEqual(len(r.data["data"]), 1)

    def test_same_filename_different_paths_not_collapsed(self):
        self._add_media(name="leaf.jpg")
        self._add_attachment(name="leaf.jpg")
        r = self.admin_client.get(self._admin_url())
        self.assertEqual(len(r.data["data"]), 2)

    def test_deterministic_ordering_by_created_at(self):
        from datetime import timedelta

        from django.utils import timezone

        later = self._add_attachment(name="later.jpg")
        earlier = self._add_media(name="earlier.jpg")
        now = timezone.now()
        VisitMedia.objects.filter(pk=earlier.pk).update(
            uploaded_at=now - timedelta(days=2),
            created_at=now - timedelta(days=2),
        )
        VisitAttachment.objects.filter(pk=later.pk).update(uploaded_at=now)
        r = self.admin_client.get(self._admin_url())
        keys = [row["source"] for row in r.data["data"]]
        self.assertEqual(keys, ["visit_media", "visit_attachment"])
