"""Face-enrollment lifecycle, shop/device safe deletion, face verification."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.models import (
    AttendanceAuditLog,
    AttendanceDevice,
    AttendanceEvent,
    FaceEnrollment,
    Shop,
)
from attendance.tests.helpers import (
    device_headers,
    make_admin,
    make_assignment,
    make_device,
    make_employee,
    make_shop,
    STRONG,
)

ADMIN = "/api/v1/admin/attendance"
DEVICE_ENROLL_URL = "/api/v1/attendance/enrollments/"
CHECKIN_URL = "/api/v1/attendance/check-in/"

FACE_BACKEND = "attendance.biometrics.FaceEnrollmentVerifier"


def _auth(client, user):
    client.force_authenticate(user=user)


class ShopDeletionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        _auth(self.client, self.admin)

    def test_empty_shop_permanently_deleted_with_flag(self):
        shop = make_shop()
        resp = self.client.delete(
            f"{ADMIN}/shops/{shop.id}/?permanent=true", {"reason": "cleanup"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["permanently_deleted"])
        self.assertFalse(Shop.objects.filter(pk=shop.pk).exists())
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="SHOP_DELETED").exists()
        )

    def test_empty_shop_delete_without_flag_archives(self):
        shop = make_shop()
        resp = self.client.delete(f"{ADMIN}/shops/{shop.id}/")
        self.assertEqual(resp.status_code, 200)
        shop.refresh_from_db()
        self.assertIsNotNone(shop.archived_at)
        self.assertFalse(shop.is_active)
        self.assertTrue(
            AttendanceAuditLog.objects.filter(action="SHOP_ARCHIVED").exists()
        )

    def test_shop_with_history_cannot_be_permanently_deleted(self):
        shop = make_shop()
        employee = make_employee()
        issued = make_device(shop)
        make_assignment(employee, shop)
        # create history: a check-in event
        AttendanceEvent.objects.create(
            employee=employee,
            shop=shop,
            device=issued.device,
            event_type="CHECK_IN",
            occurred_at=timezone.now(),
            verification_method="TEST_MANUAL",
            is_test_mode=True,
        )
        resp = self.client.delete(f"{ADMIN}/shops/{shop.id}/?permanent=true")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "SHOP_DELETE_BLOCKED")
        shop.refresh_from_db()
        self.assertIsNone(shop.archived_at)  # refused — not even archived

        # plain DELETE archives instead, preserving history
        resp = self.client.delete(f"{ADMIN}/shops/{shop.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["archived"])
        self.assertEqual(AttendanceEvent.objects.filter(shop=shop).count(), 1)

    def test_archived_shop_hidden_from_normal_list(self):
        shop = make_shop()
        self.client.delete(f"{ADMIN}/shops/{shop.id}/")
        resp = self.client.get(f"{ADMIN}/shops/")
        codes = [s["code"] for s in resp.data["results"]]
        self.assertNotIn(shop.code, codes)
        resp = self.client.get(f"{ADMIN}/shops/?include_archived=1")
        codes = [s["code"] for s in resp.data["results"]]
        self.assertIn(shop.code, codes)

    def test_dependency_summary_reported(self):
        shop = make_shop()
        employee = make_employee()
        make_device(shop)
        make_assignment(employee, shop)
        resp = self.client.get(f"{ADMIN}/shops/{shop.id}/dependency-summary/")
        deps = resp.data["data"]["dependencies"]
        self.assertEqual(deps["devices_total"], 1)
        self.assertEqual(deps["employee_assignments_total"], 1)
        self.assertFalse(resp.data["data"]["can_permanently_delete"])

    def test_staff_required(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(
            self.client.delete(f"{ADMIN}/shops/1/").status_code, 401
        )


class DeviceDeletionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        _auth(self.client, self.admin)
        self.shop = make_shop()

    def test_device_with_events_revoked_not_deleted(self):
        employee = make_employee()
        issued = make_device(self.shop)
        AttendanceEvent.objects.create(
            employee=employee, shop=shop_event(issued), device=issued.device,
            event_type="CHECK_IN", occurred_at=timezone.now(),
            verification_method="TEST_MANUAL", is_test_mode=True,
        )
        resp = self.client.delete(f"{ADMIN}/devices/{issued.device.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["permanently_deleted"])
        issued.device.refresh_from_db()
        self.assertIsNotNone(issued.device.revoked_at)

    def test_disposable_device_hard_deleted(self):
        issued = make_device(self.shop)
        resp = self.client.delete(f"{ADMIN}/devices/{issued.device.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["permanently_deleted"])
        self.assertFalse(
            AttendanceDevice.objects.filter(pk=issued.device.id).exists()
        )

    def test_revoked_device_cannot_authenticate_then_restore(self):
        issued = make_device(self.shop)
        token = issued.plaintext_token
        self.client.post(f"{ADMIN}/devices/{issued.device.id}/revoke/")
        resp = self.client.get(
            "/api/v1/attendance/employees/",
            **device_headers(issued.device.device_uid, token),
        )
        self.assertEqual(resp.status_code, 403)
        # explicit authorized restore
        resp = self.client.post(f"{ADMIN}/devices/{issued.device.id}/restore/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(
            "/api/v1/attendance/employees/",
            **device_headers(issued.device.device_uid, token),
        )
        self.assertEqual(resp.status_code, 200)


def shop_event(issued):
    return issued.device.shop


class FaceEnrollmentAdminTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client = APIClient()
        _auth(self.client, self.admin)
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)

    def _authorize(self, **overrides):
        payload = {
            "employee": self.employee.id,
            "shop": self.shop.id,
            "device": self.issued.device.id,
            "consent_recorded": True,
            **overrides,
        }
        return self.client.post(f"{ADMIN}/face-enrollments/", payload)

    def test_authorize_requires_consent(self):
        resp = self._authorize(consent_recorded=False)
        self.assertEqual(resp.status_code, 400)

    def test_authorize_requires_assignment(self):
        from attendance.models import EmployeeShopAssignment
        EmployeeShopAssignment.objects.filter(
            employee=self.employee, shop=self.shop
        ).delete()
        resp = self._authorize()
        self.assertEqual(resp.status_code, 400)

    def test_authorize_requires_matching_device_shop(self):
        other_shop = make_shop(code="SHOP-02")
        resp = self._authorize(shop=other_shop.id)
        self.assertEqual(resp.status_code, 400)

    def test_authorize_creates_pending_and_audits(self):
        resp = self._authorize()
        self.assertEqual(resp.status_code, 201)
        data = resp.data["data"]
        self.assertEqual(data["status"], "PENDING")
        self.assertTrue(data["consent_recorded"])
        self.assertTrue(
            AttendanceAuditLog.objects.filter(
                action="ENROLLMENT_AUTHORIZED"
            ).exists()
        )

    def test_reauthorize_replaces_previous(self):
        self._authorize()
        first = FaceEnrollment.objects.get()
        resp = self._authorize()
        self.assertEqual(resp.status_code, 201)
        first.refresh_from_db()
        self.assertEqual(first.status, "REPLACED")
        live = FaceEnrollment.objects.exclude(pk=first.pk).get()
        self.assertEqual(live.status, "PENDING")

    def test_revoke_blocks_completion(self):
        self._authorize()
        enrollment = FaceEnrollment.objects.get()
        resp = self.client.post(
            f"{ADMIN}/face-enrollments/{enrollment.id}/revoke/",
            {"reason": "left job"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["status"], "REVOKED")
        # kiosk can no longer complete it
        resp = self.client.post(
            f"{DEVICE_ENROLL_URL}{enrollment.id}/complete/",
            {"sample_count": 3},
            **device_headers(
                self.issued.device.device_uid, self.issued.plaintext_token
            ),
        )
        self.assertEqual(resp.status_code, 404)

    def test_employee_list_shows_enrollment_status_not_templates(self):
        self._authorize()
        resp = self.client.get(f"{ADMIN}/employees/")
        row = resp.data["results"][0]
        self.assertEqual(row["enrollment_status"], "PENDING")
        self.assertNotIn("embedding", str(row).lower())
        self.assertNotIn("template", str(row).lower())


class FaceEnrollmentDeviceTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.headers = device_headers(
            self.issued.device.device_uid, self.issued.plaintext_token
        )
        self.enrollment = FaceEnrollment.objects.create(
            employee=self.employee,
            shop=self.shop,
            device=self.issued.device,
            status=FaceEnrollment.STATUS_PENDING,
            consent_recorded=True,
            consent_at=timezone.now(),
        )

    def test_device_lists_only_own_enrollments(self):
        other = make_device(self.shop, device_uid="dev-002")
        FaceEnrollment.objects.create(
            employee=self.employee, shop=self.shop, device=other.device,
            status=FaceEnrollment.STATUS_PENDING,
        )
        resp = self.client.get(DEVICE_ENROLL_URL, **self.headers)
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]["enrollments"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["enrollment_id"], self.enrollment.id)
        self.assertEqual(rows[0]["employee_code"], "ATT-0001")
        # no biometric material in the payload
        body = str(rows).lower()
        self.assertNotIn("embedding", body)
        self.assertNotIn("image", body)

    def test_complete_flips_to_active(self):
        resp = self.client.post(
            f"{DEVICE_ENROLL_URL}{self.enrollment.id}/complete/",
            {"sample_count": 4},
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "ACTIVE")
        self.assertEqual(self.enrollment.sample_count, 4)
        self.assertIsNotNone(self.enrollment.enrolled_at)

    def test_complete_wrong_device_rejected(self):
        other = make_device(self.shop, device_uid="dev-003")
        resp = self.client.post(
            f"{DEVICE_ENROLL_URL}{self.enrollment.id}/complete/",
            {"sample_count": 4},
            **device_headers(other.device.device_uid, other.plaintext_token),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "ENROLLMENT_WRONG_DEVICE")


@override_settings(
    ATTENDANCE_BIOMETRIC_BACKEND=FACE_BACKEND,
    ATTENDANCE_FACE_VERIFICATION_ENABLED=True,
    ATTENDANCE_FACE_MIN_SCORE=0.8,
    ATTENDANCE_FACE_MAX_SKEW_SECONDS=120,
)
class FaceVerificationTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.issued = make_device(self.shop)
        self.employee = make_employee()
        make_assignment(self.employee, self.shop)
        self.headers = device_headers(
            self.issued.device.device_uid, self.issued.plaintext_token
        )
        self.enrollment = FaceEnrollment.objects.create(
            employee=self.employee,
            shop=self.shop,
            device=self.issued.device,
            status=FaceEnrollment.STATUS_ACTIVE,
            consent_recorded=True,
            consent_at=timezone.now(),
            sample_count=4,
            enrolled_at=timezone.now(),
        )

    def _payload(self, **overrides):
        payload = {
            "employee_id": self.employee.id,
            "client_event_id": "face-evt-1",
            "liveness_confirmed": True,
            "recognition_score": 0.92,
            "captured_at": timezone.now().isoformat(),
            "capture_nonce": "nonce-1",
        }
        payload.update(overrides)
        return payload

    def test_valid_face_checkin_creates_biometric_event(self):
        resp = self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        self.assertEqual(resp.status_code, 201)
        ev = resp.data["data"]["event"]
        self.assertEqual(ev["verification_method"], "BIOMETRIC")
        self.assertFalse(ev["is_test_mode"])

    def test_no_enrollment_rejected_and_audited(self):
        self.enrollment.delete()
        resp = self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "FACE_VERIFICATION_FAILED")
        self.assertTrue(
            AttendanceAuditLog.objects.filter(
                action="FACE_VERIFY_REJECTED"
            ).exists()
        )

    def test_enrollment_on_other_device_rejected(self):
        self.enrollment.device = make_device(
            self.shop, device_uid="dev-009"
        ).device
        self.enrollment.save()
        resp = self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_pending_enrollment_not_yet_valid(self):
        self.enrollment.status = FaceEnrollment.STATUS_PENDING
        self.enrollment.enrolled_at = None
        self.enrollment.save()
        resp = self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_liveness_required(self):
        resp = self.client.post(
            CHECKIN_URL,
            self._payload(liveness_confirmed=False),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_low_score_rejected(self):
        resp = self.client.post(
            CHECKIN_URL, self._payload(recognition_score=0.5), **self.headers
        )
        self.assertEqual(resp.status_code, 403)

    def test_stale_capture_timestamp_rejected(self):
        old = timezone.now() - timezone.timedelta(minutes=10)
        resp = self.client.post(
            CHECKIN_URL,
            self._payload(captured_at=old.isoformat()),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_arbitrary_employee_id_without_enrollment_rejected(self):
        stranger = make_employee(employee_code="ATT-0099")
        make_assignment(stranger, self.shop)
        resp = self.client.post(
            CHECKIN_URL,
            self._payload(employee_id=stranger.id),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_revoked_enrollment_rejected(self):
        self.enrollment.status = FaceEnrollment.STATUS_REVOKED
        self.enrollment.save()
        resp = self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_inactive_employee_rejected(self):
        self.employee.is_active = False
        self.employee.save()
        resp = self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_duplicate_client_event_id_rejected(self):
        self.client.post(CHECKIN_URL, self._payload(), **self.headers)
        other = make_employee(employee_code="ATT-0002")
        make_assignment(other, self.shop)
        FaceEnrollment.objects.create(
            employee=other, shop=self.shop, device=self.issued.device,
            status=FaceEnrollment.STATUS_ACTIVE, consent_recorded=True,
            consent_at=timezone.now(), sample_count=2,
            enrolled_at=timezone.now(),
        )
        resp = self.client.post(
            CHECKIN_URL,
            self._payload(employee_id=other.id),
            **self.headers,
        )
        self.assertEqual(resp.status_code, 409)


@override_settings(ATTENDANCE_BIOMETRIC_BACKEND=FACE_BACKEND)
class FaceDisabledTests(TestCase):
    """Real biometric stays disabled unless explicitly enabled."""

    def test_disabled_backend_unavailable(self):
        shop = make_shop()
        issued = make_device(shop)
        employee = make_employee()
        make_assignment(employee, shop)
        resp = APIClient().post(
            CHECKIN_URL,
            {
                "employee_id": employee.id,
                "liveness_confirmed": True,
                "recognition_score": 0.99,
                "captured_at": timezone.now().isoformat(),
            },
            **device_headers(issued.device.device_uid, issued.plaintext_token),
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["code"], "BIOMETRIC_UNAVAILABLE")


@override_settings(
    LOCAL_STATIC_PAIRING_ENABLED=True,
)
class StaticRevokedDeviceTests(TestCase):
    def test_revoked_static_device_not_silently_reactivated(self):
        from attendance.devices import redeem_pairing_code, PairingError

        shop = Shop.objects.create(
            code="TEST-0001", name="Test Shop", is_active=True
        )
        issued = redeem_pairing_code("246810")
        issued.device.revoked_at = timezone.now()
        issued.device.is_active = False
        issued.device.save()
        with self.assertRaises(PairingError) as cm:
            redeem_pairing_code("246810")
        self.assertEqual(cm.exception.code, "PAIRING_DEVICE_REVOKED")

    def test_deleted_static_device_can_re_pair_fresh(self):
        from attendance.devices import redeem_pairing_code

        Shop.objects.create(code="TEST-0001", name="T", is_active=True)
        issued = redeem_pairing_code("246810")
        issued.device.delete()  # disposable — no events
        again = redeem_pairing_code("246810")
        self.assertEqual(again.device.device_uid, "246810")
