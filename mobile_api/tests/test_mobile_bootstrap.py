"""Canonical mobile bootstrap contract."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmployeeDeviceSession, EmployeeProfile
from tracking.duty_service import end_duty, serialize_duty_status, start_duty
from tracking.duty_expiry import complete_duty_as_auto_expired


def _employee(username="boot_emp", employee_id="BOOT-001"):
    user = User.objects.create_user(username=username, password="secret123")
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000555",
        is_active_employee=True,
    )
    return user


class MobileBootstrapTests(TestCase):
    def setUp(self):
        self.user = _employee()
        self.client = APIClient()
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "BOOT-001",
                "password": "secret123",
                "device_name": "Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.token = r.data["access"]
        self.session_id = r.data["device_session_id"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_DEVICE_SESSION=self.session_id,
        )

    def _bootstrap(self):
        return self.client.get("/api/v1/mobile/bootstrap/")

    def test_no_duty(self):
        resp = self._bootstrap()
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIsNone(data["current_duty"])
        self.assertIsNone(data["day_map"])
        self.assertIn("server_now", data)
        self.assertEqual(data["device_session"]["status"], "ACTIVE")
        self.assertTrue(data["feature_flags"]["canonical_duty"])

    def test_active_duty(self):
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        resp = self._bootstrap()
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["current_duty"]["duty_session_id"], duty.pk)
        self.assertIsNotNone(data["day_map"])
        self.assertEqual(data["day_map"]["duty_session_id"], duty.pk)
        self.assertTrue(data["day_map"]["has_start_marker"])

        current = self.client.get("/api/v1/tracking/duty/current/")
        self.assertEqual(
            current.data["data"]["duty_session_id"],
            data["current_duty"]["duty_session_id"],
        )

    def test_completed_duty_today(self):
        start_duty(self.user, latitude=12.97, longitude=77.59)
        end_duty(self.user, latitude=12.98, longitude=77.60)
        resp = self._bootstrap()
        data = resp.data["data"]
        self.assertIsNotNone(data["current_duty"])
        self.assertFalse(data["current_duty"]["is_active"])
        self.assertEqual(data["current_duty"]["duty_status"], "COMPLETED")

    def test_expired_duty(self):
        duty = start_duty(self.user, latitude=12.97, longitude=77.59).duty
        duty.start_time = timezone.now() - timedelta(hours=10)
        duty.save(update_fields=["start_time"])
        complete_duty_as_auto_expired(duty, trigger="test")
        resp = self._bootstrap()
        data = resp.data["data"]
        self.assertIsNotNone(data["current_duty"])
        self.assertEqual(data["current_duty"]["duty_session_id"], duty.pk)

    def test_replaced_session(self):
        EmployeeDeviceSession.objects.filter(session_key=self.session_id).update(
            is_active=False
        )
        resp = self._bootstrap()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data.get("code"), "SESSION_REPLACED")

    def test_disabled_user(self):
        EmployeeProfile.objects.filter(user=self.user).update(is_active_employee=False)
        resp = self._bootstrap()
        # Device session mixin or employee gate
        self.assertIn(resp.status_code, (403, 401, 409))

    def test_server_now_and_auth_bootstrap_alias(self):
        resp = self._bootstrap()
        alias = self.client.get("/api/v1/mobile/auth/bootstrap/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(alias.status_code, 200)
        self.assertIn("T", resp.data["data"]["server_now"])
        # Same duty contract as serialize_duty_status
        expected = serialize_duty_status(self.user)
        if expected.get("duty_session_id"):
            self.assertEqual(
                resp.data["data"]["current_duty"]["duty_session_id"],
                expected["duty_session_id"],
            )
        else:
            self.assertIsNone(resp.data["data"]["current_duty"])
