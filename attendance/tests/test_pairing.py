"""6-digit device pairing flow tests."""

from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.devices import (
    authenticate_device,
    generate_pairing_code,
    hash_pairing_code,
    issue_device,
    revoke_device,
)
from attendance.models import (
    AttendanceAuditLog,
    AttendanceDevice,
    DevicePairingCode,
)
from attendance.tests.helpers import device_headers, make_admin, make_shop

PAIR_URL = "/api/v1/attendance/devices/pair/"
ADMIN_CODES_URL = "/api/v1/admin/attendance/devices/pairing-codes/"
EMPLOYEES_URL = "/api/v1/attendance/employees/"


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class PairingCodeGenerationTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.admin = make_admin()
        self.client = APIClient()

    def test_admin_generates_code(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(ADMIN_CODES_URL, {"shop_id": self.shop.id})
        self.assertEqual(resp.status_code, 201)
        code = resp.data["data"]["pairing_code"]
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertEqual(resp.data["data"]["expires_in_seconds"], 300)
        pairing = DevicePairingCode.objects.get()
        self.assertEqual(pairing.code_hash, hash_pairing_code(code))
        self.assertNotEqual(pairing.code_hash, code)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(
                action="PAIRING_CODE_ISSUED"
            ).exists()
        )

    def test_unauthenticated_rejected(self):
        resp = APIClient().post(ADMIN_CODES_URL, {"shop_id": self.shop.id})
        self.assertIn(resp.status_code, (401, 403))

    def test_non_staff_rejected(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="plain", password="SecurePass1!")
        self.client.force_authenticate(user=user)
        resp = self.client.post(ADMIN_CODES_URL, {"shop_id": self.shop.id})
        self.assertEqual(resp.status_code, 403)

    def test_inactive_shop_rejected(self):
        self.shop.is_active = False
        self.shop.save()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(ADMIN_CODES_URL, {"shop_id": self.shop.id})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_shop_rejected(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(ADMIN_CODES_URL, {"shop_id": 999999})
        self.assertEqual(resp.status_code, 400)

    def test_new_code_expires_previous(self):
        self.client.force_authenticate(user=self.admin)
        first = self.client.post(ADMIN_CODES_URL, {"shop_id": self.shop.id})
        second = self.client.post(ADMIN_CODES_URL, {"shop_id": self.shop.id})
        self.assertEqual(second.status_code, 201)
        old_code = first.data["data"]["pairing_code"]
        resp = self.client.post(PAIR_URL, {"pairing_code": old_code})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "PAIRING_CODE_USED")


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class PairingRedemptionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.shop = make_shop(code="SHOP-0001", name="Kavya Agri Clinic")
        self.admin = make_admin()
        self.client = APIClient()

    def _issue(self, shop=None):
        return generate_pairing_code(
            shop=shop or self.shop, name="", device_type="KIOSK",
            created_by=self.admin,
        )

    def test_valid_code_pairs_device(self):
        issued = self._issue()
        resp = self.client.post(
            PAIR_URL,
            {"pairing_code": issued.plaintext_code,
             "device_label": "Kavya Attendance Android"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["device_uid"], issued.device.device_uid)
        self.assertEqual(data["shop_id"], self.shop.id)
        self.assertEqual(data["shop_code"], "SHOP-0001")
        self.assertEqual(data["shop_name"], "Kavya Agri Clinic")
        self.assertTrue(data["device_token"])
        issued.device.refresh_from_db()
        self.assertTrue(issued.device.is_active)
        self.assertEqual(issued.device.name, "Kavya Attendance Android")
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="DEVICE_PAIRED").exists()
        )

    def test_wrong_code_rejected(self):
        issued = self._issue()
        wrong = f"{(int(issued.plaintext_code) + 1) % 1_000_000:06d}"
        resp = self.client.post(PAIR_URL, {"pairing_code": wrong})
        self.assertIn(resp.status_code, (400, 403))
        self.assertFalse(AttendanceDevice.objects.filter(is_active=True).exists())
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="PAIRING_FAILED").exists()
        )

    def test_expired_code_rejected(self):
        issued = self._issue()
        DevicePairingCode.objects.filter(
            device=issued.device
        ).update(expires_at=timezone.now() - timezone.timedelta(minutes=1))
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "PAIRING_CODE_EXPIRED")

    def test_used_code_rejected(self):
        issued = self._issue()
        first = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertEqual(second.status_code, 403)
        self.assertEqual(second.data["code"], "PAIRING_CODE_USED")
        # Exactly one live device resulted.
        self.assertEqual(
            AttendanceDevice.objects.filter(is_active=True).count(), 1
        )

    def test_attempt_lockout(self):
        issued = self._issue()
        DevicePairingCode.objects.filter(
            device=issued.device
        ).update(attempts=DevicePairingCode.MAX_ATTEMPTS)
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "PAIRING_CODE_LOCKED")

    def test_malformed_code_rejected(self):
        for bad in ["", "12345", "1234567", "abcdef"]:
            resp = self.client.post(PAIR_URL, {"pairing_code": bad})
            self.assertEqual(resp.status_code, 400)

    def test_device_uid_unique(self):
        a = self._issue()
        b = generate_pairing_code(
            shop=make_shop(code="SHOP-02"), name="", device_type="KIOSK"
        )
        self.assertNotEqual(a.device.device_uid, b.device.device_uid)

    def test_paired_device_authenticates(self):
        issued = self._issue()
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        token = resp.data["data"]["device_token"]
        found = authenticate_device(issued.device.device_uid, token)
        self.assertIsNotNone(found)
        resp = self.client.get(
            EMPLOYEES_URL,
            **device_headers(issued.device.device_uid, token),
        )
        self.assertEqual(resp.status_code, 200)

    def test_revoked_paired_device_cannot_authenticate(self):
        issued = self._issue()
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        token = resp.data["data"]["device_token"]
        revoke_device(issued.device)
        self.assertIsNone(authenticate_device(issued.device.device_uid, token))

    def test_no_secret_leakage_in_errors(self):
        issued = self._issue()
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertEqual(resp.status_code, 200)
        # Second use: response must not contain token or full code.
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertNotIn(issued.plaintext_code, resp.content.decode())
        self.assertNotIn("device_token", resp.data.get("data") or {})
        for log in AttendanceAuditLog.objects.all():
            self.assertNotIn(issued.plaintext_code, str(log.metadata))

    @override_settings(ATTENDANCE_PAIRING_GLOBAL_MAX_PER_MINUTE=3)
    def test_global_attempt_limit(self):
        for _ in range(3):
            self.client.post(PAIR_URL, {"pairing_code": "000000"})
        resp = self.client.post(PAIR_URL, {"pairing_code": "000000"})
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.data["code"], "PAIRING_RATE_LIMITED")


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class DeviceIdTests(TestCase):
    """Permanent 6-digit numeric Device ID behaviour."""

    def setUp(self):
        self.shop = make_shop()
        self.admin = make_admin()
        self.client = APIClient()

    def test_generated_id_is_6_digit_string(self):
        issued = issue_device(
            shop=self.shop, name="K", device_type="KIOSK"
        )
        uid = issued.device.device_uid
        self.assertIsInstance(uid, str)
        self.assertEqual(len(uid), 6)
        self.assertTrue(uid.isdigit())

    def test_leading_zeros_preserved(self):
        issued = issue_device(
            shop=self.shop, name="K", device_type="KIOSK",
            device_uid="000123",
        )
        self.assertEqual(issued.device.device_uid, "000123")

    def test_ids_unique_across_many_devices(self):
        uids = set()
        for _ in range(50):
            issued = issue_device(
                shop=self.shop, name="K", device_type="KIOSK"
            )
            uids.add(issued.device.device_uid)
        self.assertEqual(len(uids), 50)

    def test_collision_retries_until_unique(self):
        from unittest.mock import patch

        with patch(
            "attendance.devices._new_device_uid",
            side_effect=["111111", "111111", "222222"],
        ):
            first = issue_device(shop=self.shop, name="A", device_type="KIOSK")
            second = issue_device(shop=self.shop, name="B", device_type="KIOSK")
        self.assertEqual(first.device.device_uid, "111111")
        self.assertEqual(second.device.device_uid, "222222")

    def test_admin_register_auto_generates_read_only_id(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/v1/admin/attendance/devices/",
            # device_uid deliberately supplied — must be ignored
            {"shop": self.shop.id, "device_uid": "999999", "name": "K"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        uid = resp.data["data"]["device"]["device_uid"]
        self.assertNotEqual(uid, "999999")
        self.assertEqual(len(uid), 6)
        self.assertTrue(uid.isdigit())

    def test_pairing_returns_permanent_device_id(self):
        issued = generate_pairing_code(
            shop=self.shop, name="", device_type="KIOSK",
            created_by=self.admin,
        )
        uid = issued.device.device_uid
        self.assertEqual(len(uid), 6)
        self.assertTrue(uid.isdigit())
        # pairing code and permanent device id are separate values
        resp = self.client.post(
            PAIR_URL, {"pairing_code": issued.plaintext_code}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["device_uid"], uid)

    def test_legacy_uid_devices_still_authenticate(self):
        legacy = issue_device(
            shop=self.shop, name="Old", device_type="KIOSK",
            device_uid="dev-001",
        )
        found = authenticate_device("dev-001", legacy.plaintext_token)
        self.assertIsNotNone(found)


@override_settings(ATTENDANCE_TEST_MODE_ENABLED=True)
class PairingHttpsTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = generate_pairing_code(
            shop=self.shop, name="", device_type="KIOSK"
        )
        self.client = APIClient()

    @override_settings(ATTENDANCE_PAIRING_REQUIRE_HTTPS=True)
    def test_http_pairing_rejected(self):
        resp = self.client.post(
            PAIR_URL, {"pairing_code": self.issued.plaintext_code}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "PAIRING_HTTPS_REQUIRED")

    @override_settings(ATTENDANCE_PAIRING_REQUIRE_HTTPS=True)
    def test_https_pairing_accepted(self):
        resp = self.client.post(
            PAIR_URL,
            {"pairing_code": self.issued.plaintext_code},
            secure=True,
        )
        self.assertEqual(resp.status_code, 200)
