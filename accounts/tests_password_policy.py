"""Regression tests for the 8-character strong password policy."""

from __future__ import annotations

from django.contrib.auth.hashers import get_hasher
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.credentials import generate_temporary_password
from accounts.models import EmployeeProfile
from accounts.password_policy import MIN_PASSWORD_LENGTH, validate_strong_password
from audit_logs.models import AuditLog


ADMIN_PASSWORD = "AdminPass1!x"
EMP_A_PASSWORD = "EmployeeA1!x"
EMP_B_PASSWORD = "EmployeeB2!y"


def _make_admin():
    user = User.objects.create_user(
        username="pw_policy_admin",
        password=ADMIN_PASSWORD,
        is_staff=True,
        is_active=True,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="ADM-PWP",
        phone="9000000101",
        role="Supervisor",
        is_active_employee=True,
        can_login=True,
    )
    return user


def _make_employee(*, username: str, employee_id: str, password: str):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_staff=False,
        is_active=True,
    )
    profile = EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000102",
        role="FieldAgent",
        is_active_employee=True,
        can_login=True,
    )
    return user, profile


class PasswordPolicyUnitTests(TestCase):
    def test_minimum_length_is_eight(self):
        self.assertEqual(MIN_PASSWORD_LENGTH, 8)

    def test_seven_char_rejected(self):
        with self.assertRaises(ValidationError):
            validate_strong_password("Ka@0003")

    def test_valid_eight_char_accepted(self):
        validate_strong_password("Kavi@000")

    def test_valid_nine_char_accepted(self):
        validate_strong_password("Kavi@0003")

    def test_example_policy_passwords_accepted(self):
        for password in ("Kavi@0003", "Sasi@0004", "Rama@0011"):
            validate_strong_password(password)

    def test_generated_temp_password_length_unchanged(self):
        password = generate_temporary_password()
        self.assertGreaterEqual(len(password), 10)
        self.assertRegex(password, r"^Kac@[A-Z0-9]{6}$")
        validate_strong_password(password)

    def test_missing_uppercase_rejected(self):
        with self.assertRaises(ValidationError):
            validate_strong_password("kavi@0003")

    def test_missing_lowercase_rejected(self):
        with self.assertRaises(ValidationError):
            validate_strong_password("KAVI@0003")

    def test_missing_number_rejected(self):
        with self.assertRaises(ValidationError):
            validate_strong_password("Kavi@@@@")

    def test_missing_symbol_rejected(self):
        with self.assertRaises(ValidationError):
            validate_strong_password("Kavi0003")

    def test_pbkdf2_hasher_unchanged(self):
        hasher = get_hasher()
        self.assertEqual(hasher.algorithm, "pbkdf2_sha256")
        self.assertEqual(hasher.iterations, 1_000_000)


class AdminResetPasswordPolicyTests(TestCase):
    def setUp(self):
        self.admin = _make_admin()
        self.emp_a, self.profile_a = _make_employee(
            username="pw_emp_a",
            employee_id="KAC-PWA1",
            password=EMP_A_PASSWORD,
        )
        self.emp_b, self.profile_b = _make_employee(
            username="pw_emp_b",
            employee_id="KAC-PWB1",
            password=EMP_B_PASSWORD,
        )
        self.hash_a_before = self.emp_a.password
        self.hash_b_before = self.emp_b.password
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.url = "/api/v1/employees/admin/reset-password/"

    def test_admin_reset_accepts_valid_eight_char_password(self):
        new_password = "Kavi@000"
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile_a.employee_id, "new_password": new_password},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.emp_a.refresh_from_db()
        self.assertTrue(self.emp_a.check_password(new_password))
        self.assertFalse(self.emp_a.check_password(EMP_A_PASSWORD))
        self.assertNotEqual(self.emp_a.password, self.hash_a_before)

    def test_admin_reset_rejects_seven_char_password(self):
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile_a.employee_id, "new_password": "Ka@0003"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.emp_a.refresh_from_db()
        self.assertEqual(self.emp_a.password, self.hash_a_before)
        self.assertTrue(self.emp_a.check_password(EMP_A_PASSWORD))

    def test_unrelated_employee_unchanged_after_reset(self):
        resp = self.client.post(
            self.url,
            {
                "employee_id": self.profile_a.employee_id,
                "new_password": "Sasi@0004",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        self.emp_b.refresh_from_db()
        self.profile_b.refresh_from_db()
        self.assertEqual(self.emp_b.password, self.hash_b_before)
        self.assertTrue(self.emp_b.check_password(EMP_B_PASSWORD))
        self.assertTrue(self.emp_b.is_active)
        self.assertTrue(self.profile_b.is_active_employee)
        self.assertTrue(self.profile_b.can_login)
        self.assertEqual(self.emp_b.username, "pw_emp_b")

    def test_policy_change_alone_does_not_modify_existing_hashes(self):
        """Existing hashes remain valid until an explicit reset."""
        self.emp_a.refresh_from_db()
        self.emp_b.refresh_from_db()
        self.assertEqual(self.emp_a.password, self.hash_a_before)
        self.assertEqual(self.emp_b.password, self.hash_b_before)
        self.assertTrue(self.emp_a.check_password(EMP_A_PASSWORD))
        self.assertTrue(self.emp_b.check_password(EMP_B_PASSWORD))

    def test_reset_response_contains_no_plaintext_password(self):
        new_password = "Rama@0011"
        resp = self.client.post(
            self.url,
            {"employee_id": self.profile_a.employee_id, "new_password": new_password},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        blob = str(resp.data)
        self.assertNotIn(new_password, blob)
        self.assertNotIn("new_password", blob)

        logs = AuditLog.objects.filter(
            module="AUTH", action="PASSWORD_CHANGE", object_id=str(self.emp_a.id)
        )
        self.assertTrue(logs.exists())
        for log in logs:
            meta = str(log.metadata or {})
            self.assertNotIn(new_password, meta)
            self.assertNotIn(new_password, log.description or "")

    def test_staff_cannot_reset_owner_superuser(self):
        owner = User.objects.create_user(
            username="pw_owner_target",
            password=ADMIN_PASSWORD,
            is_staff=True,
            is_superuser=True,
        )
        owner_profile = EmployeeProfile.objects.create(
            user=owner,
            employee_id="OWN-PWP",
            phone="9000000199",
            role="Owner",
            is_active_employee=True,
            can_login=True,
        )
        owner_hash = owner.password
        resp = self.client.post(
            self.url,
            {"employee_id": owner_profile.employee_id, "new_password": "Kavi@0003"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        owner.refresh_from_db()
        self.assertEqual(owner.password, owner_hash)
        self.assertTrue(owner.check_password(ADMIN_PASSWORD))


class ChangePasswordPolicyTests(TestCase):
    def setUp(self):
        self.emp, self.profile = _make_employee(
            username="pw_change_emp",
            employee_id="KAC-PWC1",
            password=EMP_A_PASSWORD,
        )
        from accounts.device_sessions import register_device_session

        session = register_device_session(
            self.emp, request_data={"device_id": "pw-change-device"}
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.emp)
        self.client.credentials(HTTP_X_DEVICE_SESSION=str(session.session_key))
        self.url = "/api/v1/employees/change-password/"

    def test_change_password_accepts_valid_eight_char(self):
        new_password = "Kavi@000"
        resp = self.client.post(
            self.url,
            {
                "current_password": EMP_A_PASSWORD,
                "new_password": new_password,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password(new_password))
        self.assertNotIn(new_password, str(resp.data))

    def test_change_password_rejects_missing_symbol(self):
        resp = self.client.post(
            self.url,
            {
                "current_password": EMP_A_PASSWORD,
                "new_password": "Kavi0003",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password(EMP_A_PASSWORD))
