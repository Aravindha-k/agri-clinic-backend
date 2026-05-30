from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeProfile
from mobile_api.test_helpers import login_mobile_client
from masters.models import Crop, District, Farmer, Village
from visits.attachments import MAX_ATTACHMENT_BYTES
from visits.models import Visit, VisitAttachment


class VisitAttachmentAPITest(APITestCase):
    def setUp(self):
        self.employee_a = User.objects.create_user(username="emp_att_a", password="x")
        self.employee_b = User.objects.create_user(username="emp_att_b", password="x")
        EmployeeProfile.objects.create(
            user=self.employee_a,
            employee_id="EMP-ATT-A",
            phone="9000000301",
            is_active_employee=True,
        )
        EmployeeProfile.objects.create(
            user=self.employee_b,
            employee_id="EMP-ATT-B",
            phone="9000000302",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="admin_att", password="x", is_staff=True, is_superuser=True
        )

        district = District.objects.create(name="Att District")
        village = Village.objects.create(name="Att Village", district=district)
        self.farmer = Farmer.objects.create(
            name="Attachment Farmer",
            phone="9888777666",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Maize", name_ta="Maize", is_active=True)

        self.client_a = login_mobile_client(employee_id="EMP-ATT-A")
        self.client_b = login_mobile_client(employee_id="EMP-ATT-B")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

        payload = {
            "farmer": self.farmer.id,
            "crop": self.crop.id,
            "latitude": 12.97,
            "longitude": 77.59,
        }
        r = self.client_a.post("/api/v1/mobile/visits/", payload, format="json")
        self.assertEqual(r.status_code, 200)
        self.visit_id = r.data["data"]["visit_id"]

        r2 = self.client_b.post("/api/v1/mobile/visits/", payload, format="json")
        self.other_visit_id = r2.data["data"]["visit_id"]

    def _image_file(self, name="proof.jpg", size=1024):
        return SimpleUploadedFile(
            name,
            b"x" * size,
            content_type="image/jpeg",
        )

    def test_employee_upload_image(self):
        url = f"/api/v1/mobile/visits/{self.visit_id}/attachments/"
        r = self.client_a.post(
            url,
            {"attachment_type": "image", "file": self._image_file()},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["success"])
        self.assertEqual(r.data["data"]["attachment_type"], "image")
        self.assertIn("file_url", r.data["data"])
        self.assertTrue(r.data["data"]["file_url"].startswith("http"))

    def test_employee_upload_text_note(self):
        url = f"/api/v1/mobile/visits/{self.visit_id}/attachments/"
        r = self.client_a.post(
            url,
            {"attachment_type": "text", "text_content": "Farmer reported pest damage."},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["data"]["attachment_type"], "text")
        self.assertEqual(
            r.data["data"]["text_content"], "Farmer reported pest damage."
        )
        self.assertIsNone(r.data["data"]["file_url"])

    def test_employee_cannot_access_other_employee_visit(self):
        url = f"/api/v1/mobile/visits/{self.other_visit_id}/attachments/"
        r = self.client_a.get(url)
        self.assertIn(r.status_code, (403, 404))

        r2 = self.client_a.post(
            url,
            {"attachment_type": "image", "file": self._image_file()},
            format="multipart",
        )
        self.assertIn(r2.status_code, (403, 404))

    def test_admin_can_view_attachments(self):
        create = self.client_a.post(
            f"/api/v1/mobile/visits/{self.visit_id}/attachments/",
            {"attachment_type": "image", "file": self._image_file()},
            format="multipart",
        )
        self.assertEqual(create.status_code, 201)

        admin_url = f"/api/v1/admin/visits/{self.visit_id}/attachments/"
        r = self.admin_client.get(admin_url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["success"])
        self.assertEqual(len(r.data["data"]), 1)

        detail = self.admin_client.get(f"/api/v1/admin/visits/{self.visit_id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(detail.data["attachments"]), 1)

    def test_invalid_file_type_rejected(self):
        bad = SimpleUploadedFile(
            "virus.exe",
            b"bad",
            content_type="application/octet-stream",
        )
        r = self.client_a.post(
            f"/api/v1/mobile/visits/{self.visit_id}/attachments/",
            {"attachment_type": "image", "file": bad},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.data["success"])

    def test_file_size_validation(self):
        huge = self._image_file(size=MAX_ATTACHMENT_BYTES + 1)
        r = self.client_a.post(
            f"/api/v1/mobile/visits/{self.visit_id}/attachments/",
            {"attachment_type": "image", "file": huge},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("10 MB", str(r.data))

    def test_delete_own_attachment(self):
        r = self.client_a.post(
            f"/api/v1/mobile/visits/{self.visit_id}/attachments/",
            {"attachment_type": "image", "file": self._image_file()},
            format="multipart",
        )
        att_id = r.data["data"]["id"]
        d = self.client_a.delete(
            f"/api/v1/mobile/visits/{self.visit_id}/attachments/{att_id}/"
        )
        self.assertEqual(d.status_code, 200)
        self.assertEqual(
            VisitAttachment.objects.filter(visit_id=self.visit_id).count(), 0
        )
