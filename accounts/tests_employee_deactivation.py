"""Deactivated field employees must not login or continue mobile sessions."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.device_sessions import get_active_device_session, register_device_session
from accounts.employee_access import set_field_employee_active
from accounts.models import EmployeeDeviceSession, EmployeeProfile
from accounts.token_refresh import attach_device_session_claim, issue_rotated_tokens


STRONG_PASSWORD = "FieldPass1!x"


class DeactivatedEmployeeMobileAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="kac.admin.deact",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_active=True,
        )
        self.owner = User.objects.create_superuser(
            username="kac.owner.deact",
            password=STRONG_PASSWORD,
            email="owner-deact@example.com",
        )
        EmployeeProfile.objects.create(
            user=self.owner,
            employee_id="OWN-DEACT",
            phone="9000000001",
            is_active_employee=True,
            can_login=True,
        )

        self.employee = User.objects.create_user(
            username="KAC-DEACTEMP01",
            password=STRONG_PASSWORD,
            is_staff=False,
            is_active=True,
            first_name="Deact",
        )
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="KAC-8801",
            phone="9876508801",
            is_active_employee=True,
            can_login=True,
            role="FieldAgent",
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.mobile = APIClient()

    def _login(self, password=STRONG_PASSWORD):
        return self.mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "username": self.employee.username,
                "password": password,
                "device_name": "Pixel",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )

    def _auth_mobile(self, access, session_id):
        self.mobile.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}",
            HTTP_X_DEVICE_SESSION=session_id,
        )

    def _toggle_admin(self):
        return self.admin_client.patch(
            f"/api/v1/employees/admin/employees/{self.profile.id}/toggle-status/"
        )

    def test_active_employee_mobile_login_ok(self):
        r = self._login()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        self.assertTrue(
            EmployeeDeviceSession.objects.filter(
                user=self.employee, is_active=True
            ).exists()
        )

    def test_deactivate_blocks_login_and_revokes_session(self):
        login = self._login()
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)
        access = login.data["access"]
        refresh = login.data["refresh"]
        session_id = login.data["device_session_id"]

        toggle = self._toggle_admin()
        self.assertEqual(toggle.status_code, status.HTTP_200_OK, toggle.data)

        self.profile.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertFalse(self.profile.is_active_employee)
        self.assertFalse(self.profile.can_login)
        self.assertFalse(self.employee.is_active)
        self.assertFalse(
            EmployeeDeviceSession.objects.filter(
                user=self.employee, is_active=True
            ).exists()
        )

        denied = self._login()
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN, denied.data)
        self.assertEqual(denied.data.get("code"), "EMPLOYEE_INACTIVE")
        self.assertNotIn("access", denied.data)

        refresh_r = self.mobile.post(
            "/api/v1/mobile/auth/refresh/",
            {"refresh": refresh, "device_session_id": session_id},
            format="json",
        )
        self.assertEqual(refresh_r.status_code, status.HTTP_403_FORBIDDEN, refresh_r.data)
        self.assertEqual(refresh_r.data.get("code"), "EMPLOYEE_INACTIVE")

        self._auth_mobile(access, session_id)
        me = self.mobile.get("/api/v1/mobile/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_403_FORBIDDEN, me.data)
        self.assertEqual(me.data.get("code"), "EMPLOYEE_INACTIVE")

        duty = self.mobile.post("/api/v1/tracking/duty/start/", {}, format="json")
        self.assertEqual(duty.status_code, status.HTTP_403_FORBIDDEN, duty.data)
        self.assertEqual(duty.data.get("code"), "EMPLOYEE_INACTIVE")

        gps = self.mobile.post(
            "/api/tracking/location/update/",
            {"latitude": 12.97, "longitude": 77.59},
            format="json",
        )
        self.assertEqual(gps.status_code, status.HTTP_403_FORBIDDEN, gps.data)
        self.assertEqual(gps.data.get("code"), "EMPLOYEE_INACTIVE")

        visits = self.mobile.get("/api/v1/mobile/visits/")
        self.assertEqual(visits.status_code, status.HTTP_403_FORBIDDEN, visits.data)
        self.assertEqual(visits.data.get("code"), "EMPLOYEE_INACTIVE")

    def test_reactivate_allows_login_and_new_session(self):
        self.assertEqual(self._login().status_code, status.HTTP_200_OK)
        self.assertEqual(self._toggle_admin().status_code, status.HTTP_200_OK)
        self.assertEqual(self._login().status_code, status.HTTP_403_FORBIDDEN)

        reactivate = self._toggle_admin()
        self.assertEqual(reactivate.status_code, status.HTTP_200_OK, reactivate.data)
        self.profile.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertTrue(self.profile.is_active_employee)
        self.assertTrue(self.profile.can_login)
        self.assertTrue(self.employee.is_active)

        login = self._login()
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)
        self.assertIn("device_session_id", login.data)
        self.assertTrue(
            EmployeeDeviceSession.objects.filter(
                user=self.employee,
                session_key=login.data["device_session_id"],
                is_active=True,
            ).exists()
        )

    def test_staff_admin_cannot_deactivate_owner(self):
        owner_profile = self.owner.employee_profile
        blocked = self.admin_client.patch(
            f"/api/v1/employees/admin/employees/{owner_profile.id}/toggle-status/"
        )
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertTrue(owner_profile.is_active_employee)

    def test_other_active_employee_unaffected(self):
        other = User.objects.create_user(
            username="KAC-OTHER01",
            password=STRONG_PASSWORD,
            is_staff=False,
            is_active=True,
        )
        EmployeeProfile.objects.create(
            user=other,
            employee_id="KAC-8802",
            phone="9876508802",
            is_active_employee=True,
            can_login=True,
        )
        self.assertEqual(self._toggle_admin().status_code, status.HTTP_200_OK)

        other_login = self.mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "username": "KAC-OTHER01",
                "password": STRONG_PASSWORD,
                "device_name": "Pixel",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(other_login.status_code, status.HTTP_200_OK, other_login.data)

    def test_assert_skips_users_without_employee_profile(self):
        """Shared farmer APIs historically allowed authenticated users with no profile."""
        from accounts.employee_access import assert_field_employee_may_authenticate

        orphan = User.objects.create_user(username="orphan_no_profile", password=STRONG_PASSWORD)
        assert_field_employee_may_authenticate(orphan)

    def test_set_field_employee_active_helper_revokes_without_ending_duty_contract(self):
        """Deactivation revokes device auth; duty lifecycle stays independent."""
        session = register_device_session(
            self.employee,
            request_data={"device_name": "Pixel", "platform": "android"},
        )
        self.assertIsNotNone(get_active_device_session(self.employee))
        tokens = issue_rotated_tokens(
            self.employee, device_session_id=str(session.session_key)
        )
        refresh = RefreshToken(tokens["refresh"])
        attach_device_session_claim(refresh, session.session_key)

        set_field_employee_active(self.profile, active=False, reason="unit")
        self.assertIsNone(get_active_device_session(self.employee))
