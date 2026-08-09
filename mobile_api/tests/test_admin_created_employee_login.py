"""Admin-created employees must be able to mobile-login with clear error codes."""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeDeviceSession, EmployeeProfile


STRONG_PASSWORD = "MobilePass1!"


class AdminCreatedEmployeeMobileLoginTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_create_test",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _create_legacy(self, first_name="NewAgent", phone="9876543210"):
        return self.client.post(
            "/api/v1/employees/create/",
            {
                "first_name": first_name,
                "phone": phone,
            },
            format="json",
        )

    def _create_full(
        self,
        first_name="FullAgent",
        employee_id="EMP-NEW99",
        phone="9876543211",
        role="FieldAgent",
    ):
        return self.client.post(
            "/api/v1/employees/admin/employees/",
            {
                "first_name": first_name,
                "phone": phone,
                "employee_id": employee_id,
                "role": role,
            },
            format="json",
        )

    def test_legacy_create_returns_string_employee_id_not_user_pk(self):
        r = self._create_legacy()
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        data = r.data.get("data") or r.data
        employee_id = data["employee_id"]
        self.assertIsInstance(employee_id, str)
        self.assertTrue(employee_id.startswith("KAC-"))
        self.assertNotEqual(employee_id, str(data.get("user_id")))
        self.assertTrue(data.get("can_login"))
        self.assertTrue(data.get("mobile_login_enabled"))
        self.assertTrue(data.get("account_active"))
        self.assertEqual(data.get("role"), "FieldAgent")
        self.assertEqual(data.get("username"), "KAC-NEWAGENT01")
        self.assertRegex(data.get("temporary_password") or "", r"^Kac@[A-Z0-9]{6}$")

        profile = EmployeeProfile.objects.get(employee_id=employee_id)
        self.assertTrue(profile.user.check_password(data["temporary_password"]))
        self.assertTrue(profile.user.password.startswith("pbkdf2_"))
        self.assertNotEqual(profile.user.password, data["temporary_password"])
        self.assertTrue(profile.user.is_active)
        self.assertTrue(profile.can_login)
        self.assertTrue(profile.is_active_employee)

    def test_admin_created_employee_can_mobile_login_with_employee_id(self):
        created = self._create_legacy(first_name="LoginEid")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        data = created.data.get("data") or created.data
        employee_id = data["employee_id"]
        temp_password = data["temporary_password"]

        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": employee_id,
                "password": temp_password,
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertIn("access", r.data)
        self.assertIn("device_session_id", r.data)
        self.assertEqual(r.data["user"]["employee_id"], employee_id)
        self.assertTrue(
            EmployeeDeviceSession.objects.filter(
                session_key=r.data["device_session_id"], is_active=True
            ).exists()
        )

    def test_username_login_works_for_admin_created_employee(self):
        created = self._create_legacy(first_name="LoginUser")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        data = created.data.get("data") or created.data

        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "username": data["username"],
                "password": data["temporary_password"],
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

    def test_full_admin_create_employee_id_login(self):
        created = self._create_full()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        data = created.data.get("data") or created.data
        self.assertEqual(data["employee_id"], "EMP-NEW99")
        self.assertTrue(data["mobile_login_enabled"])
        self.assertEqual(data["username"], "KAC-FULLAGENT01")

        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "EMP-NEW99",
                "password": data["temporary_password"],
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

        bootstrap = mobile.get(
            "/api/v1/mobile/auth/bootstrap/",
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )
        self.assertEqual(bootstrap.status_code, status.HTTP_200_OK, bootstrap.data)

    def test_wrong_password_returns_invalid_credentials(self):
        created = self._create_legacy(first_name="WrongPw", phone="9876543220")
        employee_id = (created.data.get("data") or created.data)["employee_id"]
        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": employee_id,
                "password": "WrongPass1!",
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED, r.data)
        self.assertEqual(r.data.get("code"), "INVALID_CREDENTIALS")

    def test_login_with_numeric_user_pk_as_employee_id_is_invalid_credentials(self):
        """Regression: admin UI used to show user.id as employee_id."""
        created = self._create_legacy(first_name="PkConfusion", phone="9876543221")
        data = created.data.get("data") or created.data
        user_id = data["user_id"]
        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": str(user_id),
                "password": data["temporary_password"],
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED, r.data)
        self.assertEqual(r.data.get("code"), "INVALID_CREDENTIALS")

    def test_inactive_employee_denied_with_account_inactive(self):
        created = self._create_legacy(first_name="InactiveEmp", phone="9876543222")
        data = created.data.get("data") or created.data
        employee_id = data["employee_id"]
        temp_password = data["temporary_password"]
        profile = EmployeeProfile.objects.get(employee_id=employee_id)
        profile.is_active_employee = False
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        profile.save(update_fields=["is_active_employee"])

        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": employee_id,
                "password": temp_password,
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.data)
        self.assertEqual(r.data.get("code"), "EMPLOYEE_INACTIVE")

    def test_can_login_false_denied_with_login_disabled(self):
        created = self._create_legacy(first_name="NoLoginEmp", phone="9876543223")
        data = created.data.get("data") or created.data
        employee_id = data["employee_id"]
        temp_password = data["temporary_password"]
        profile = EmployeeProfile.objects.get(employee_id=employee_id)
        profile.can_login = False
        profile.save(update_fields=["can_login"])

        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": employee_id,
                "password": temp_password,
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.data)
        self.assertEqual(r.data.get("code"), "EMPLOYEE_INACTIVE")

    def test_missing_profile_denied_clearly(self):
        user = User.objects.create_user(
            username="no_profile_user",
            password=STRONG_PASSWORD,
            is_staff=False,
            is_active=True,
        )
        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "username": user.username,
                "password": STRONG_PASSWORD,
                "device_name": "Pixel Test",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.data)
        self.assertEqual(r.data.get("code"), "EMPLOYEE_PROFILE_MISSING")

    def test_duplicate_employee_id_rejected(self):
        first = self._create_full(
            first_name="DupOne", employee_id="DUP-001", phone="9876543230"
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        second = self._create_full(
            first_name="DupTwo", employee_id="DUP-001", phone="9876543231"
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST, second.data)

    def test_toggle_status_also_updates_can_login(self):
        created = self._create_legacy(first_name="ToggleEmp", phone="9876543232")
        data = created.data.get("data") or created.data
        profile_id = data["id"]
        employee_id = data["employee_id"]
        profile = EmployeeProfile.objects.get(pk=profile_id)
        self.assertTrue(profile.can_login)

        off = self.client.post(f"/api/v1/employees/{employee_id}/toggle/")
        self.assertEqual(off.status_code, status.HTTP_200_OK, off.data)
        profile.refresh_from_db()
        profile.user.refresh_from_db()
        self.assertFalse(profile.is_active_employee)
        self.assertFalse(profile.can_login)
        self.assertFalse(profile.user.is_active)
