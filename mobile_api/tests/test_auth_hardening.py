"""Phase 1 authentication hardening tests."""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import EmployeeDeviceSession, EmployeeProfile
from tracking.duty_service import start_duty
from tracking.models import DutySession


STRONG_PASSWORD = "SecurePass1!"


class AuthHardeningTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(
            username="auth_emp", password=STRONG_PASSWORD
        )
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="AH-001",
            phone="9000000111",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()

    def _mobile_login(self, **extra):
        payload = {
            "employee_id": "AH-001",
            "password": STRONG_PASSWORD,
            "device_name": "Phone A",
            "platform": "android",
            "app_version": "2.0.0",
            "device_id": "device-a",
        }
        payload.update(extra)
        return self.client.post(
            "/api/v1/mobile/auth/login/", payload, format="json"
        )

    def test_logout_invalidates_refresh_token(self):
        login = self._mobile_login()
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        refresh = login.data["refresh"]
        access = login.data["access"]
        session_id = login.data["device_session_id"]

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}",
            HTTP_X_DEVICE_SESSION=session_id,
        )
        logout = self.client.post(
            "/api/v1/mobile/auth/logout/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(logout.status_code, status.HTTP_200_OK)
        self.assertFalse(
            EmployeeDeviceSession.objects.filter(
                user=self.employee, is_active=True
            ).exists()
        )

        retry = self.client.post(
            "/api/v1/mobile/auth/refresh/",
            {"refresh": refresh, "device_session_id": session_id},
            format="json",
        )
        self.assertIn(
            retry.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_409_CONFLICT),
        )

    def test_old_phone_cannot_refresh_after_new_login(self):
        first = self._mobile_login(device_id="phone-1", device_name="Phone 1")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        old_refresh = first.data["refresh"]
        old_session = first.data["device_session_id"]

        second = self._mobile_login(device_id="phone-2", device_name="Phone 2")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertNotEqual(old_session, second.data["device_session_id"])

        rejected = self.client.post(
            "/api/v1/mobile/auth/refresh/",
            {"refresh": old_refresh, "device_session_id": old_session},
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(rejected.data.get("code"), "SESSION_REPLACED")

        ok = self.client.post(
            "/api/v1/mobile/auth/refresh/",
            {
                "refresh": second.data["refresh"],
                "device_session_id": second.data["device_session_id"],
            },
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertIn("access", ok.data)
        self.assertIn("refresh", ok.data)

    def test_old_phone_loses_write_access_after_new_login(self):
        first = self._mobile_login(device_id="phone-1")
        second = self._mobile_login(device_id="phone-2")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {first.data['access']}",
            HTTP_X_DEVICE_SESSION=first.data["device_session_id"],
        )
        conflict = self.client.get("/api/v1/mobile/auth/me/")
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {second.data['access']}",
            HTTP_X_DEVICE_SESSION=second.data["device_session_id"],
        )
        ok = self.client.get("/api/v1/mobile/auth/me/")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)

    def test_disabled_user_cannot_refresh(self):
        login = self._mobile_login()
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.profile.can_login = False
        self.profile.save(update_fields=["can_login"])

        refresh = self.client.post(
            "/api/v1/mobile/auth/refresh/",
            {
                "refresh": login.data["refresh"],
                "device_session_id": login.data["device_session_id"],
            },
            format="json",
        )
        self.assertEqual(refresh.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh.data.get("code"), "ACCOUNT_DISABLED")

    def test_logout_does_not_end_duty_session(self):
        login = self._mobile_login()
        duty = start_duty(self.employee, latitude=12.0, longitude=79.0).duty
        self.assertTrue(duty.is_active)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
            HTTP_X_DEVICE_SESSION=login.data["device_session_id"],
        )
        self.client.post(
            "/api/v1/mobile/auth/logout/",
            {"refresh": login.data["refresh"]},
            format="json",
        )
        duty.refresh_from_db()
        self.assertTrue(duty.is_active)
        self.assertEqual(
            DutySession.objects.filter(user=self.employee, is_active=True).count(), 1
        )

    def test_device_replacement_does_not_end_duty(self):
        first = self._mobile_login(device_id="phone-1")
        duty = start_duty(self.employee, latitude=12.0, longitude=79.0).duty
        started_at = duty.start_time
        second = self._mobile_login(device_id="phone-2")
        duty.refresh_from_db()
        self.assertTrue(duty.is_active)
        self.assertEqual(duty.start_time, started_at)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {second.data['access']}",
            HTTP_X_DEVICE_SESSION=second.data["device_session_id"],
        )
        current = self.client.get("/api/tracking/duty/current/")
        self.assertEqual(current.status_code, status.HTTP_200_OK)

    def test_web_refresh_blocks_disabled_employee(self):
        web = self.client.post(
            "/api/v1/auth/login/",
            {"username": "auth_emp", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(web.status_code, status.HTTP_200_OK)
        self.profile.can_login = False
        self.profile.save(update_fields=["can_login"])
        refresh = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": web.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh.data.get("code"), "ACCOUNT_DISABLED")

    def test_web_login_does_not_replace_mobile_device_session(self):
        mobile = self._mobile_login(device_id="phone-mobile")
        session_id = mobile.data["device_session_id"]
        web = self.client.post(
            "/api/v1/auth/login/",
            {"username": "auth_emp", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(web.status_code, status.HTTP_200_OK)
        self.assertTrue(
            EmployeeDeviceSession.objects.filter(
                user=self.employee, session_key=session_id, is_active=True
            ).exists()
        )


@override_settings(
    ADMIN_LOGIN_MAX_ATTEMPTS=5,
    ADMIN_LOGIN_LOCKOUT_MINUTES=15,
    ADMIN_SESSION_TIMEOUT_MINUTES=30,
    ADMIN_IP_WHITELIST_ENABLED=False,
)
class AdminShortSessionRefreshTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="auth_admin",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()

    def test_admin_refresh_keeps_short_access_lifetime(self):
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "auth_admin", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        refresh = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": login.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, status.HTTP_200_OK)
        access = AccessToken(refresh.data["access"])
        lifetime = access["exp"] - access["iat"]
        # Admin session timeout is 30 minutes (± a few seconds)
        self.assertLessEqual(lifetime, 30 * 60 + 5)
        self.assertGreaterEqual(lifetime, 29 * 60)


class RefreshOrderTests(TestCase):
    """Refresh must validate device before issuing new tokens."""

    def setUp(self):
        self.employee = User.objects.create_user(
            username="order_emp", password=STRONG_PASSWORD
        )
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="OR-001",
            phone="9000000444",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()

    def test_revoked_device_does_not_rotate_tokens(self):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        first = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "OR-001",
                "password": STRONG_PASSWORD,
                "device_id": "old",
            },
            format="json",
        )
        old_refresh = first.data["refresh"]
        old_session = first.data["device_session_id"]
        blacklisted_before = BlacklistedToken.objects.count()

        self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "OR-001",
                "password": STRONG_PASSWORD,
                "device_id": "new",
            },
            format="json",
        )

        rejected = self.client.post(
            "/api/v1/mobile/auth/refresh/",
            {"refresh": old_refresh, "device_session_id": old_session},
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_409_CONFLICT)
        # Old refresh must not be rotated/blacklisted-as-success path after device fail
        # (may or may not blacklist depending on whether Token() load blacklists;
        #  critical: no new access/refresh returned)
        self.assertNotIn("access", rejected.data)
        self.assertNotIn("refresh", rejected.data)
