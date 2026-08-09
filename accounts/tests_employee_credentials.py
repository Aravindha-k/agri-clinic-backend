"""Auto username + temporary-password generation for field employees."""

from __future__ import annotations

import re
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.credentials import (
    create_field_employee_with_generated_credentials,
    generate_employee_username,
    generate_temporary_password,
    normalize_first_name_for_username,
)
from accounts.models import EmployeeProfile
from audit_logs.models import AuditLog


STRONG_PASSWORD = "OwnerPass1!x"


class UsernameNormalizationTests(TestCase):
    def test_normalize_first_name(self):
        self.assertEqual(normalize_first_name_for_username(" Aravindh "), "ARAVINDH")
        self.assertEqual(normalize_first_name_for_username("Ravi Kumar"), "RAVIKUMAR")
        self.assertEqual(normalize_first_name_for_username("Su@resh!!"), "SURESH")

    def test_password_format(self):
        for _ in range(20):
            pw = generate_temporary_password()
            self.assertRegex(pw, r"^Kac@[A-Z0-9]{6}$")


class EmployeeCredentialGenerationAPITests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="kac.admin.cred",
            password=STRONG_PASSWORD,
            is_staff=True,
            is_active=True,
        )
        self.owner = User.objects.create_superuser(
            username="kac.owner.cred",
            password=STRONG_PASSWORD,
            email="owner-cred@example.com",
        )
        EmployeeProfile.objects.create(
            user=self.owner,
            employee_id="OWN-CRED",
            phone="9000000001",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _create(self, first_name, phone="9876500001", **extra):
        body = {"first_name": first_name, "phone": phone, **extra}
        return self.client.post("/api/v1/employees/create/", body, format="json")

    def _create_full(self, first_name, phone="9876500002", **extra):
        body = {
            "first_name": first_name,
            "phone": phone,
            "role": "FieldAgent",
            **extra,
        }
        return self.client.post(
            "/api/v1/employees/admin/employees/", body, format="json"
        )

    def test_first_aravindh_username(self):
        r = self._create("Aravindh", phone="9876500101")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        data = r.data["data"]
        self.assertEqual(data["username"], "KAC-ARAVINDH01")
        self.assertRegex(data["temporary_password"], r"^Kac@[A-Z0-9]{6}$")
        user = User.objects.get(username="KAC-ARAVINDH01")
        self.assertTrue(user.check_password(data["temporary_password"]))
        self.assertTrue(user.password.startswith("pbkdf2_"))

    def test_second_aravindh_increments(self):
        self.assertEqual(
            self._create("Aravindh", phone="9876500102").status_code,
            status.HTTP_201_CREATED,
        )
        r = self._create("Aravindh", phone="9876500103")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data["data"]["username"], "KAC-ARAVINDH02")

    def test_first_ravi(self):
        r = self._create("Ravi", phone="9876500104")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data["data"]["username"], "KAC-RAVI01")

    def test_sequence_uses_max_not_count(self):
        User.objects.create_user(username="KAC-RAVI01", password=STRONG_PASSWORD)
        User.objects.create_user(username="KAC-RAVI03", password=STRONG_PASSWORD)
        self.assertEqual(generate_employee_username("Ravi"), "KAC-RAVI04")
        r = self._create("Ravi", phone="9876500105")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data["data"]["username"], "KAC-RAVI04")

    def test_owner_admin_usernames_unchanged(self):
        self.assertTrue(User.objects.filter(username="kac.owner.cred").exists())
        self.assertTrue(User.objects.filter(username="kac.admin.cred").exists())
        self._create("Aravindh", phone="9876500106")
        self.assertTrue(User.objects.filter(username="kac.owner.cred").exists())
        self.assertTrue(User.objects.filter(username="kac.admin.cred").exists())

    def test_create_admin_still_requires_username_password(self):
        owner_client = APIClient()
        owner_client.force_authenticate(user=self.owner)
        r = owner_client.post(
            "/api/v1/employees/create-admin/",
            {
                "username": "staff.manual.admin",
                "password": STRONG_PASSWORD,
                "phone": "9000000098",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertTrue(User.objects.filter(username="staff.manual.admin").exists())
        self.assertFalse(
            User.objects.filter(username__startswith="KAC-STAFF").exists()
        )

    def test_temporary_password_absent_on_get(self):
        created = self._create_full("Suresh", phone="9876500107")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        data = created.data["data"]
        self.assertIn("temporary_password", data)
        profile_id = data["id"]

        detail = self.client.get(f"/api/v1/employees/admin/employees/{profile_id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        detail_data = detail.data.get("data") or detail.data
        self.assertNotIn("temporary_password", detail_data)
        if isinstance(detail_data, dict) and "username" in detail_data:
            self.assertEqual(detail_data["username"], "KAC-SURESH01")

        listing = self.client.get("/api/v1/employees/admin/employees/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        blob = str(listing.data)
        self.assertNotIn("temporary_password", blob)
        self.assertNotIn("Kac@", blob)

    def test_edit_first_name_does_not_regenerate_username_or_password(self):
        created = self._create("Ravi", phone="9876500108")
        data = created.data["data"]
        username = data["username"]
        temp = data["temporary_password"]
        profile_id = data["id"]
        user = User.objects.get(username=username)

        patch = self.client.patch(
            f"/api/v1/employees/admin/employees/{profile_id}/",
            {"first_name": "Ravikumar"},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.data)
        user.refresh_from_db()
        self.assertEqual(user.username, username)
        self.assertEqual(user.first_name, "Ravikumar")
        self.assertTrue(user.check_password(temp))
        patch_data = patch.data.get("data") or patch.data
        self.assertNotIn("temporary_password", str(patch_data))

    def test_audit_log_excludes_temporary_password(self):
        r = self._create("Aravindh", phone="9876500109")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        logs = AuditLog.objects.filter(
            module="ACCOUNTS", action="CREATE", object_id=r.data["data"]["user_id"]
        )
        self.assertTrue(logs.exists())
        for log in logs:
            meta = log.metadata or {}
            self.assertNotIn("temporary_password", meta)
            self.assertNotIn("password", meta)
            blob = str(meta)
            self.assertNotIn("Kac@", blob)

    def test_legacy_username_password_ignored(self):
        r = self._create(
            "Aravindh",
            phone="9876500110",
            username="should.be.ignored",
            password=STRONG_PASSWORD,
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data["data"]["username"], "KAC-ARAVINDH01")
        self.assertFalse(User.objects.filter(username="should.be.ignored").exists())
        user = User.objects.get(username="KAC-ARAVINDH01")
        self.assertFalse(user.check_password(STRONG_PASSWORD))
        self.assertTrue(user.check_password(r.data["data"]["temporary_password"]))

    def test_mobile_login_with_generated_credentials(self):
        created = self._create("Aravindh", phone="9876500111")
        data = created.data["data"]
        mobile = APIClient()
        r = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "username": data["username"],
                "password": data["temporary_password"],
                "device_name": "Pixel",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertIn("access", r.data)

        r2 = mobile.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": data["employee_id"],
                "password": data["temporary_password"],
                "device_name": "Pixel",
                "platform": "android",
            },
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)

    def test_employee_id_still_kac_numeric(self):
        r = self._create("Aravindh", phone="9876500112")
        eid = r.data["data"]["employee_id"]
        self.assertTrue(re.match(r"^KAC-\d{4,}$", eid), eid)
        self.assertNotEqual(eid, r.data["data"]["username"])


class UsernameCollisionRetryTests(TestCase):
    def test_integrity_error_retries_next_username(self):
        User.objects.create_user(username="KAC-ARAVINDH01", password=STRONG_PASSWORD)
        calls = {"n": 0}
        real_create = User.objects.create_user

        def flaky_create_user(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("duplicate key value violates unique constraint")
            return real_create(*args, **kwargs)

        with mock.patch.object(
            User.objects, "create_user", side_effect=flaky_create_user
        ):
            profile = create_field_employee_with_generated_credentials(
                first_name="Aravindh",
                phone="9876599999",
            )
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(profile.user.username, "KAC-ARAVINDH02")
        temp = getattr(profile, "_temporary_password")
        self.assertRegex(temp, r"^Kac@[A-Z0-9]{6}$")
        self.assertTrue(profile.user.check_password(temp))
