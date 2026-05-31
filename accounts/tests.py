from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from rest_framework import status

from .models import EmployeeProfile

OLD_EMP_PASSWORD = "Oldsecret123!"
NEW_EMP_PASSWORD = "Newsecret456!"
RESET_EMP_PASSWORD = "Adminreset99!"
ORIGINAL_EMP_PASSWORD = "Originalpass1!"


def make_admin(username="admin", password="adminpass"):
    """Helper: create a Django staff user with an EmployeeProfile."""
    user = User.objects.create_user(
        username=username, password=password, is_staff=True, is_active=True
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id=f"ADM-{user.id:04d}",
        phone="9000000001",
        role="Supervisor",
    )
    return user


def make_employee(username="emp001", password="emppass", employee_id="KAC-0001"):
    """Helper: create a regular employee."""
    user = User.objects.create_user(
        username=username, password=password, is_staff=False, is_active=True
    )
    EmployeeProfile.objects.create(
        user=user, employee_id=employee_id, phone="9000000002", role="FieldAgent"
    )
    return user


def auth_client(user):
    """Return an authenticated APIClient for the given user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# =============================================================
# 1. EMPLOYEE UPDATE
# =============================================================
class EmployeeUpdateTests(TestCase):

    def setUp(self):
        self.admin = make_admin()
        self.emp = make_employee()
        self.profile = self.emp.employee_profile
        self.client = auth_client(self.admin)
        self.url = f"/api/v1/employees/{self.profile.id}/"

    def test_patch_first_last_name(self):
        resp = self.client.patch(
            self.url,
            {"first_name": "Ravi", "last_name": "Kumar"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["first_name"], "Ravi")
        self.assertEqual(data["data"]["last_name"], "Kumar")
        # Verify persisted
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.first_name, "Ravi")
        self.assertEqual(self.emp.last_name, "Kumar")

    def test_patch_phone(self):
        resp = self.client.patch(self.url, {"phone": "9876543210"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.phone, "9876543210")

    def test_patch_phone_invalid(self):
        resp = self.client.patch(self.url, {"phone": "abc"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()["success"])

    def test_patch_role(self):
        resp = self.client.patch(self.url, {"role": "Supervisor"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, "Supervisor")

    def test_put_updates_multiple_fields(self):
        resp = self.client.put(
            self.url,
            {
                "first_name": "Muthu",
                "last_name": "Vel",
                "phone": "9111111111",
                "role": "Supervisor",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["success"])
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.first_name, "Muthu")

    def test_response_never_contains_password(self):
        resp = self.client.patch(self.url, {"phone": "9111222233"}, format="json")
        self.assertNotIn("password", resp.json().get("data", {}))


# =============================================================
# 2. TOGGLE ACTIVE / INACTIVE
# =============================================================
class ToggleActiveTests(TestCase):

    def setUp(self):
        self.admin = make_admin()
        self.emp = make_employee()
        self.profile = self.emp.employee_profile
        self.client = auth_client(self.admin)

    def test_toggle_via_patch_is_active_false(self):
        """PATCH /employees/{id}/ with is_active_employee=false deactivates."""
        url = f"/api/v1/employees/{self.profile.id}/"
        resp = self.client.patch(url, {"is_active_employee": False}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.emp.refresh_from_db()
        self.assertFalse(self.profile.is_active_employee)
        self.assertFalse(self.emp.is_active)  # Django user.is_active also updated

    def test_toggle_via_patch_is_active_true(self):
        """Re-activate a disabled employee."""
        self.profile.is_active_employee = False
        self.emp.is_active = False
        self.profile.save(update_fields=["is_active_employee"])
        self.emp.save(update_fields=["is_active"])

        url = f"/api/v1/employees/{self.profile.id}/"
        resp = self.client.patch(url, {"is_active_employee": True}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_active_employee)

    def test_toggle_via_toggle_status_endpoint(self):
        """/employees/{str}/toggle/ flips the status."""
        url = f"/api/v1/employees/{self.profile.employee_id}/toggle/"
        resp = self.client.post(url, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_active_employee)  # was True → False

    def test_toggle_reflected_in_list(self):
        """After toggle, list endpoint returns updated state."""
        toggle_url = f"/api/v1/employees/{self.profile.employee_id}/toggle/"
        self.client.post(toggle_url)
        list_resp = self.client.get("/api/v1/employees/")
        payload = list_resp.json()
        employees = payload.get("results") or payload.get("data", {}).get("results") or []
        match = next(
            (e for e in employees if e["employee_id"] == self.profile.employee_id), None
        )
        self.assertIsNotNone(match)
        self.assertFalse(match["is_active_employee"])


# =============================================================
# 3. CHANGE PASSWORD (self-service)
# =============================================================
class ChangePasswordTests(TestCase):

    def setUp(self):
        self.emp = make_employee(username="fielduser", password=OLD_EMP_PASSWORD)
        self.profile = self.emp.employee_profile
        self.client = auth_client(self.emp)  # authenticated as the employee
        self.url = "/api/v1/employees/change-password/"

    def test_wrong_current_password_returns_error(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": "WRONGPASSWORD",
                "new_password": NEW_EMP_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()["success"])
        # Ensure old password still works
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password(OLD_EMP_PASSWORD))

    def test_correct_current_password_changes_successfully(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": OLD_EMP_PASSWORD,
                "new_password": NEW_EMP_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["success"])
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password(NEW_EMP_PASSWORD))
        self.assertFalse(self.emp.check_password(OLD_EMP_PASSWORD))

    def test_unknown_employee_id_returns_error(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": "NON-EXISTENT",
                "current_password": OLD_EMP_PASSWORD,
                "new_password": NEW_EMP_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()["success"])

    def test_password_not_exposed_in_response(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": OLD_EMP_PASSWORD,
                "new_password": NEW_EMP_PASSWORD,
            },
            format="json",
        )
        body = resp.json()
        self.assertNotIn(OLD_EMP_PASSWORD, str(body))
        self.assertNotIn(NEW_EMP_PASSWORD, str(body))

    def test_unauthenticated_request_rejected(self):
        client = APIClient()  # no auth
        resp = client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": OLD_EMP_PASSWORD,
                "new_password": NEW_EMP_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# =============================================================
# 4. ADMIN RESET PASSWORD (no current password required)
# =============================================================
class AdminResetPasswordTests(TestCase):

    def setUp(self):
        self.admin = make_admin()
        self.emp = make_employee(username="target_user", password=ORIGINAL_EMP_PASSWORD)
        self.profile = self.emp.employee_profile
        self.client = auth_client(self.admin)
        self.url = "/api/v1/employees/admin/reset-password/"

    def test_admin_can_reset_without_current_password(self):
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile.employee_id, "new_password": RESET_EMP_PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["success"])
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password(RESET_EMP_PASSWORD))

    def test_non_admin_cannot_reset_password(self):
        non_admin_client = auth_client(self.emp)
        resp = non_admin_client.post(
            self.url,
            {"employee_id": self.profile.employee_id, "new_password": "Hack1234!"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_employee_id_returns_error(self):
        resp = self.client.post(
            self.url,
            {"employee_id": "GHOST-0000", "new_password": "Ghost1234!"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_response_does_not_expose_password(self):
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile.employee_id, "new_password": RESET_EMP_PASSWORD},
            format="json",
        )
        self.assertNotIn(RESET_EMP_PASSWORD, str(resp.json()))


class ProfilePhotoAPITest(APITestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from masters.models import Crop, District, Farmer, Village
        from visits.models import Visit

        self._SimpleUploadedFile = SimpleUploadedFile
        self.admin = User.objects.create_user(
            username="admin_photo", password="x", is_staff=True, is_superuser=True
        )
        self.employee = User.objects.create_user(username="emp_photo", password="x")
        self.other = User.objects.create_user(username="emp_other", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-PHOTO-1",
            phone="9000000401",
            is_active_employee=True,
        )
        EmployeeProfile.objects.create(
            user=self.other,
            employee_id="EMP-PHOTO-2",
            phone="9000000402",
            is_active_employee=True,
        )
        district = District.objects.create(name="Photo D")
        village = Village.objects.create(name="Photo V", district=district)
        self.farmer = Farmer.objects.create(
            name="Photo Farmer",
            phone="9111222333",
            district=district,
            village=village,
            created_by_employee=self.employee,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            crop=self.crop,
            latitude=12.97,
            longitude=77.59,
        )

        from mobile_api.test_helpers import login_mobile_client

        self.emp_client = login_mobile_client(employee_id="EMP-PHOTO-1")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _photo(self, name="me.jpg"):
        return self._SimpleUploadedFile(name, b"imgbytes", content_type="image/jpeg")

    def test_employee_upload_own_photo_mobile(self):
        r = self.emp_client.patch(
            "/api/v1/mobile/profile/photo/",
            {"profile_photo": self._photo()},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["success"])
        self.assertIn("profile_photo_url", r.data["data"])
        self.assertIn("profile_photo_updated_at", r.data["data"])

    def test_employee_upload_own_photo_me_alias(self):
        r = self.emp_client.patch(
            "/api/v1/employees/me/photo/",
            {"profile_photo": self._photo("me-alias.jpg")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("profile_photo_url", r.data["data"])

    def test_admin_upload_employee_photo(self):
        profile = self.employee.employee_profile
        r = self.admin_client.patch(
            f"/api/v1/admin/employees/{profile.id}/photo/",
            {"profile_photo": self._photo("admin-emp.jpg")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200)

    def test_invalid_photo_type_rejected(self):
        bad = self._SimpleUploadedFile(
            "x.exe", b"z", content_type="application/octet-stream"
        )
        r = self.emp_client.patch(
            "/api/v1/mobile/profile/photo/",
            {"profile_photo": bad},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
