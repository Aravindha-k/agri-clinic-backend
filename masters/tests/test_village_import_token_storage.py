"""Village import token storage: shared across workers, lifecycle security."""

from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path
from django.contrib.auth.models import User
from django.core.cache import caches
from django.core.cache.backends.filebased import FileBasedCache
from django.core.cache.backends.locmem import LocMemCache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.models import Village
from masters.operational_village_import import (
    IMPORT_CACHE_PREFIX,
    IMPORT_TOKEN_CACHE_ALIAS,
    VillageImportError,
    collect_plan,
    discard_import_token,
    load_and_consume_import_plan,
    store_import_plan,
)

STRONG = "SecurePass1!"
VALIDATE_URL = "/api/v1/admin/villages/import/validate/"
CONFIRM_URL = "/api/v1/admin/villages/import/confirm/"


def _xlsx(rows):
    book = Workbook()
    sheet = book.active
    sheet.append(["Employee ID", "Employee Name", "Village", "Village Tamil Name"])
    for row in rows:
        sheet.append(row)
    buf = BytesIO()
    book.save(buf)
    book.close()
    return SimpleUploadedFile(
        "villages.xlsx",
        buf.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


class LocMemMultiWorkerFailureEvidenceTests(TestCase):
    """Prove LocMem is process-local (multi-worker TOKEN_INVALID root cause)."""

    def test_locmem_instances_do_not_share_keys(self):
        worker_a = LocMemCache("worker-a", {})
        worker_b = LocMemCache("worker-b", {})
        worker_a.set("village_import_plan:v1:demo", {"ok": True}, timeout=60)
        self.assertIsNone(worker_b.get("village_import_plan:v1:demo"))

    def test_filebased_instances_with_same_location_share_keys(self):
        # FileBasedCache(dir, params) — first arg is the directory path.
        with tempfile.TemporaryDirectory() as tmp:
            worker_a = FileBasedCache(tmp, {})
            worker_b = FileBasedCache(tmp, {})
            worker_a.set("village_import_plan:v1:demo", {"ok": True}, timeout=60)
            self.assertEqual(worker_b.get("village_import_plan:v1:demo"), {"ok": True})


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "village-import-token-default",
        },
        "import_tokens": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(
                Path(tempfile.gettempdir()) / "agri_clinic_import_tokens_test"
            ),
            "TIMEOUT": 1800,
        },
    }
)
class VillageImportTokenLifecycleTests(TestCase):
    def setUp(self):
        caches[IMPORT_TOKEN_CACHE_ALIAS].clear()
        self.admin_a = User.objects.create_user(
            username="token_admin_a", password=STRONG, is_staff=True
        )
        self.admin_b = User.objects.create_user(
            username="token_admin_b", password=STRONG, is_staff=True
        )
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.admin_a)
        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.admin_b)

        self.emp_user = User.objects.create_user(
            username="rajiv_tok", password=STRONG, first_name="Rajiv"
        )
        self.emp = EmployeeProfile.objects.create(
            user=self.emp_user,
            employee_id="KAC-0008",
            phone="9000000008",
            role="FieldAgent",
        )
        self.emp2_user = User.objects.create_user(
            username="uthira_tok", password=STRONG, first_name="Uthira"
        )
        self.emp2 = EmployeeProfile.objects.create(
            user=self.emp2_user,
            employee_id="KAC-0009",
            phone="9000000009",
            role="FieldAgent",
        )

    def _validate(self, client, rows):
        return client.post(VALIDATE_URL, {"file": _xlsx(rows)}, format="multipart")

    def test_validate_returns_token_and_immediate_confirm_succeeds(self):
        validate = self._validate(
            self.client_a, [["KAC-0008", "Rajiv", "Aasur", "ஆசூர்"]]
        )
        self.assertEqual(validate.status_code, status.HTTP_200_OK)
        data = validate.json()["data"]
        self.assertTrue(data["can_confirm"])
        token = data["import_token"]
        self.assertTrue(token)

        confirm = self.client_a.post(
            CONFIRM_URL, {"import_token": token}, format="json"
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK, confirm.data)
        self.assertEqual(confirm.json()["data"]["assignments_created"], 1)
        self.assertEqual(Village.objects.filter(name="Aasur").count(), 1)

    def test_second_confirm_rejected(self):
        validate = self._validate(
            self.client_a, [["KAC-0008", "Rajiv", "ReplayV", "ரீப்"]]
        )
        token = validate.json()["data"]["import_token"]
        first = self.client_a.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = self.client_a.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(second.json().get("code"), {"TOKEN_REPLAY", "TOKEN_INVALID"})
        self.assertEqual(Village.objects.filter(name="ReplayV").count(), 1)

    def test_invalid_token_rejected(self):
        resp = self.client_a.post(
            CONFIRM_URL, {"import_token": "not-a-real-token"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json().get("code"), "TOKEN_INVALID")

    def test_expired_token_rejected(self):
        upload = _xlsx([["KAC-0008", "Rajiv", "ExpireV", ""]])
        plan = collect_plan(upload)
        token = store_import_plan(plan=plan, user_id=self.admin_a.pk)
        discard_import_token(token)  # simulate TTL expiry / eviction
        with self.assertRaises(VillageImportError) as ctx:
            load_and_consume_import_plan(token=token, user_id=self.admin_a.pk)
        self.assertEqual(ctx.exception.code, "TOKEN_INVALID")

    def test_token_bound_to_admin_user(self):
        validate = self._validate(
            self.client_a, [["KAC-0008", "Rajiv", "BoundV", ""]]
        )
        token = validate.json()["data"]["import_token"]
        forbidden = self.client_b.post(
            CONFIRM_URL, {"import_token": token}, format="json"
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.json().get("code"), "TOKEN_FORBIDDEN")
        # Original admin can still confirm
        ok = self.client_a.post(CONFIRM_URL, {"import_token": token}, format="json")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)

    def test_service_replay_before_discard_returns_token_replay(self):
        upload = _xlsx([["KAC-0008", "Rajiv", "ReplaySvc", ""]])
        plan = collect_plan(upload)
        token = store_import_plan(plan=plan, user_id=self.admin_a.pk)
        load_and_consume_import_plan(token=token, user_id=self.admin_a.pk)
        with self.assertRaises(VillageImportError) as ctx:
            load_and_consume_import_plan(token=token, user_id=self.admin_a.pk)
        self.assertEqual(ctx.exception.code, "TOKEN_REPLAY")

    def test_token_readable_via_independent_cache_handle(self):
        """Simulate another worker reading the same shared FileBased LOCATION."""
        upload = _xlsx([["KAC-0008", "Rajiv", "SharedCacheV", ""]])
        plan = collect_plan(upload)
        token = store_import_plan(plan=plan, user_id=self.admin_a.pk)
        key = f"{IMPORT_CACHE_PREFIX}{token}"

        # Clear default LocMem — must not affect import_tokens.
        caches["default"].clear()
        self.assertIsNotNone(caches[IMPORT_TOKEN_CACHE_ALIAS].get(key))

        shared = caches[IMPORT_TOKEN_CACHE_ALIAS]
        # New backend handle pointing at the same on-disk directory (other worker).
        other = FileBasedCache(shared._dir, {})
        payload = other.get(key)
        self.assertIsNotNone(payload)
        self.assertEqual(int(payload["user_id"]), self.admin_a.pk)

    def test_shared_kollaar_import_still_works(self):
        validate = self._validate(
            self.client_a,
            [
                ["KAC-0008", "Rajiv", "Kollaar", "கொள்ளார்"],
                ["KAC-0009", "Uthira", "Kollaar", "கொள்ளார்"],
            ],
        )
        data = validate.json()["data"]
        self.assertTrue(data["can_confirm"])
        self.assertEqual(len(data["shared_villages"]), 1)
        confirm = self.client_a.post(
            CONFIRM_URL, {"import_token": data["import_token"]}, format="json"
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertEqual(Village.objects.filter(name="Kollaar").count(), 1)
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                village__name="Kollaar", is_operational=True
            ).count(),
            2,
        )

    def test_duplicate_aasur_same_employee_idempotent(self):
        validate = self._validate(
            self.client_a,
            [
                ["KAC-0008", "Rajiv", "Aasur", "ஆசூர்"],
                ["KAC-0008", "Rajiv", "Aasur", "ஆசூர்"],
            ],
        )
        data = validate.json()["data"]
        self.assertEqual(data["assignments_to_create"], 1)
        confirm = self.client_a.post(
            CONFIRM_URL, {"import_token": data["import_token"]}, format="json"
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm.json()["data"]["assignments_created"], 1)
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                employee=self.emp, village__name="Aasur"
            ).count(),
            1,
        )

    def test_clearing_default_locmem_does_not_invalidate_import_token(self):
        """Regression: tokens must not live in LocMem default cache."""
        validate = self._validate(
            self.client_a, [["KAC-0008", "Rajiv", "LocMemSafe", ""]]
        )
        token = validate.json()["data"]["import_token"]
        caches["default"].clear()
        confirm = self.client_a.post(
            CONFIRM_URL, {"import_token": token}, format="json"
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK, confirm.data)
