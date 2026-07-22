from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.device_sessions import DEVICE_SESSION_HEADER
from accounts.models import EmployeeProfile


class CanLoginEnforcementTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="canlogin_emp", password="Secret12345")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="CL-001",
            phone="9000000999",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()

    def _mobile_login(self):
        return self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "CL-001",
                "password": "Secret12345",
                "device_name": "Pixel Test",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )

    def test_mobile_login_blocked_when_can_login_false(self):
        self.profile.can_login = False
        self.profile.save(update_fields=["can_login"])
        r = self._mobile_login()
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data.get("code"), "LOGIN_DISABLED")

    def test_web_login_blocked_when_can_login_false(self):
        self.profile.can_login = False
        self.profile.save(update_fields=["can_login"])
        r = self.client.post(
            "/api/v1/auth/login/",
            {"username": "canlogin_emp", "password": "Secret12345"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data.get("code"), "ACCOUNT_DISABLED")

    def test_mobile_me_blocked_after_can_login_disabled(self):
        r = self._mobile_login()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.profile.can_login = False
        self.profile.save(update_fields=["can_login"])
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )
        me = self.client.get("/api/v1/mobile/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_403_FORBIDDEN)

    def test_mobile_refresh_blocked_when_can_login_false(self):
        r = self._mobile_login()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.profile.can_login = False
        self.profile.save(update_fields=["can_login"])
        refresh = self.client.post(
            "/api/v1/mobile/auth/refresh/",
            {"refresh": r.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh.data.get("code"), "ACCOUNT_DISABLED")


class LegacyVisitDeviceSessionTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="leg_emp", password="Secret12345")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="LG-001",
            phone="9000000777",
            is_active_employee=True,
            can_login=True,
        )
        self.admin = User.objects.create_user(
            username="leg_admin", password="Secret12345", is_staff=True
        )
        self.client = APIClient()

    def _mobile_login(self):
        return self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "LG-001",
                "password": "Secret12345",
                "device_name": "Pixel Test",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )

    def test_legacy_visits_list_requires_device_session_for_employee(self):
        r = self._mobile_login()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        blocked = self.client.get("/api/v1/visits/")
        self.assertEqual(blocked.status_code, status.HTTP_409_CONFLICT)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )
        ok = self.client.get("/api/v1/visits/")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)

    def test_admin_can_list_legacy_visits_without_device_session(self):
        self.client.force_authenticate(user=self.admin)
        ok = self.client.get("/api/v1/visits/")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
