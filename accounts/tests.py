from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from .models import EmployeeProfile


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
        employees = list_resp.json()["data"]
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
        self.emp = make_employee(username="fielduser", password="oldsecret123")
        self.profile = self.emp.employee_profile
        self.client = auth_client(self.emp)  # authenticated as the employee
        self.url = "/api/v1/employees/change-password/"

    def test_wrong_current_password_returns_error(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": "WRONGPASSWORD",
                "new_password": "newsecret456",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.json()["success"])
        # Ensure old password still works
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("oldsecret123"))

    def test_correct_current_password_changes_successfully(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": "oldsecret123",
                "new_password": "newsecret456",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["success"])
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("newsecret456"))
        self.assertFalse(self.emp.check_password("oldsecret123"))

    def test_unknown_employee_id_returns_error(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": "NON-EXISTENT",
                "current_password": "oldsecret123",
                "new_password": "newsecret456",
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
                "current_password": "oldsecret123",
                "new_password": "newsecret456",
            },
            format="json",
        )
        body = resp.json()
        self.assertNotIn("password", str(body))
        self.assertNotIn("new_password", str(body))

    def test_unauthenticated_request_rejected(self):
        client = APIClient()  # no auth
        resp = client.post(
            self.url,
            {
                "employee_id": self.profile.employee_id,
                "current_password": "oldsecret123",
                "new_password": "newsecret456",
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
        self.emp = make_employee(username="target_user", password="originalpass")
        self.profile = self.emp.employee_profile
        self.client = auth_client(self.admin)
        self.url = "/api/v1/employees/admin/reset-password/"

    def test_admin_can_reset_without_current_password(self):
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile.employee_id, "new_password": "adminreset99"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["success"])
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("adminreset99"))

    def test_non_admin_cannot_reset_password(self):
        non_admin_client = auth_client(self.emp)
        resp = non_admin_client.post(
            self.url,
            {"employee_id": self.profile.employee_id, "new_password": "hack123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_employee_id_returns_error(self):
        resp = self.client.post(
            self.url,
            {"employee_id": "GHOST-0000", "new_password": "abc123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_response_does_not_expose_password(self):
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile.employee_id, "new_password": "adminreset99"},
            format="json",
        )
        self.assertNotIn("password", str(resp.json()))
