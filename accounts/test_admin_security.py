from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import AdminSecurityState, AdminSession
from accounts.password_policy import validate_strong_password
from audit_logs.models import AuditLog


STRONG_PASSWORD = "SecurePass1!"


class StrongPasswordPolicyTest(TestCase):
    def test_weak_password_rejected(self):
        with self.assertRaises(Exception):
            validate_strong_password("short")

    def test_strong_password_accepted(self):
        validate_strong_password(STRONG_PASSWORD)


@override_settings(
    ADMIN_LOGIN_MAX_ATTEMPTS=5,
    ADMIN_LOGIN_LOCKOUT_MINUTES=15,
    ADMIN_SESSION_TIMEOUT_MINUTES=30,
    ADMIN_IP_WHITELIST_ENABLED=False,
)
class AdminLoginSecurityTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="sec_admin",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()

    def _login(self, password=STRONG_PASSWORD):
        return self.client.post(
            "/api/v1/auth/login/",
            {"username": "sec_admin", "password": password},
            format="json",
        )

    def test_successful_admin_login_creates_session_and_audit(self):
        r = self._login()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("admin", r.data)
        self.assertTrue(
            AdminSession.objects.filter(user=self.admin, is_active=True).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin, module="AUTH", action="LOGIN"
            ).exists()
        )
        state = AdminSecurityState.objects.get(user=self.admin)
        self.assertIsNotNone(state.last_login_at)
        self.assertEqual(state.failed_login_attempts, 0)

    def test_account_locks_after_five_failed_attempts(self):
        for _ in range(5):
            self._login(password="WrongPass1!")
        r = self._login()
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data.get("code"), "ACCOUNT_LOCKED")

    def test_admin_session_expires_after_inactivity(self):
        r = self._login()
        token = r.data["access"]
        state = AdminSecurityState.objects.get(user=self.admin)
        state.last_activity_at = timezone.now() - timedelta(minutes=31)
        state.save(update_fields=["last_activity_at"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = self.client.get("/api/v1/employees/admin/security/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(ADMIN_IP_WHITELIST_ENABLED=True, ADMIN_ALLOWED_IPS=["10.0.0.1"])
class AdminIPWhitelistTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="ip_admin",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()

    def test_admin_login_blocked_from_non_whitelisted_ip(self):
        r = self.client.post(
            "/api/v1/auth/login/",
            {"username": "ip_admin", "password": STRONG_PASSWORD},
            format="json",
            REMOTE_ADDR="192.168.1.50",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data.get("code"), "IP_NOT_ALLOWED")


class AdminSecurityMonitoringTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="mon_admin",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_monitoring_endpoint_returns_admin_status(self):
        AdminSecurityState.objects.create(
            user=self.admin,
            failed_login_attempts=2,
            last_login_at=timezone.now(),
        )
        AdminSession.objects.create(
            user=self.admin,
            is_active=True,
            last_activity_at=timezone.now(),
            ip_address="127.0.0.1",
        )
        r = self.client.get("/api/v1/employees/admin/security/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["success"])
        admins = r.data["data"]["admins"]
        self.assertEqual(len(admins), 1)
        self.assertEqual(admins[0]["failed_login_attempts"], 2)
        self.assertEqual(admins[0]["active_session_count"], 1)
