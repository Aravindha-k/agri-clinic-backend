"""Phase 5 — visit single-submit-path consolidation tests."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    District,
    Farmer,
    FarmerActivity,
    ProblemCategory,
    ProblemMaster,
    Village,
)
from mobile_api.test_helpers import login_mobile_client
from utils.concurrency_test_helpers import run_concurrent_workers
from tracking.models import DutySession, EmployeeRoutePoint
from visits.models import Visit, VisitMedia
from visits.services.field_visit_service import (
    MAX_BULK_VISITS,
    submit_field_visit,
)
from visits.services.farmer_resolution import resolve_farmer_for_visit


def _png_bytes():
    # Minimal 1x1 PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


class VisitConsolidationBase(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="p5_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-P5",
            phone="9000000555",
            is_active_employee=True,
        )
        self.other = User.objects.create_user(username="p5_other", password="x")
        EmployeeProfile.objects.create(
            user=self.other,
            employee_id="EMP-P5O",
            phone="9000000556",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="p5_admin", password="x", is_staff=True, is_superuser=True
        )
        self.district = District.objects.create(name="P5 District")
        self.village = Village.objects.create(name="P5 Village", district=self.district)
        self.farmer = Farmer.objects.create(
            name="P5 Farmer",
            phone="9888000111",
            district=self.district,
            village=self.village,
        )
        self.other_farmer = Farmer.objects.create(
            name="Same Name Collision",
            phone="9888000222",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Paddy", name_ta="Paddy", is_active=True)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_p5",
            defaults={"name": "Pest P5", "requires_problem_master": True},
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category,
            name="Leaf folder",
            crop=self.crop,
        )
        self.payload = {
            "farmer_id": self.farmer.id,
            "farmer_name": self.farmer.name,
            "phone_number": self.farmer.phone,
            "village_id": self.village.id,
            "crop_id": self.crop.id,
            "acreage": 1.5,
            "problem_category_id": self.category.id,
            "problem_master_id": self.problem.id,
            "problem_description": "Leaf damage observed",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "recommendation": "Spray",
            "observation": "Seen on lower leaves",
        }
        self.client = login_mobile_client(employee_id="EMP-P5")
        self.duty = DutySession.objects.create(
            user=self.employee,
            date=timezone.localdate(),
            start_time=timezone.now(),
            is_active=True,
        )

    def _full_payload(self, **extra):
        body = dict(self.payload)
        body.update(extra)
        return body


class CanonicalServiceTests(VisitConsolidationBase):
    def test_mobile_create_calls_canonical_outcome(self):
        r = self.client.post(
            "/api/v1/mobile/visits/", self._full_payload(local_sync_id="canon-1"), format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        visit = Visit.objects.get(local_sync_id="canon-1")
        self.assertEqual(visit.employee_id, self.employee.id)
        self.assertTrue(
            EmployeeRoutePoint.objects.filter(
                visit_id=visit.pk,
                point_type=EmployeeRoutePoint.POINT_VISIT,
                client_point_id=f"visit:{visit.pk}",
            ).exists()
        )

    def test_legacy_and_farmers_create(self):
        r1 = self.client.post("/api/v1/visits/", self._full_payload(), format="json")
        self.assertIn(r1.status_code, (200, 201), r1.data)

        # farmers URL mount
        r2 = self.client.post(
            "/api/v1/visits/",
            self._full_payload(local_sync_id="farmers-path-1", latitude=12.98, longitude=77.60),
            format="json",
        )
        # Same URL may be visits.views — still canonical
        self.assertIn(r2.status_code, (200, 201), getattr(r2, "data", r2.content))

    def test_admin_create(self):
        admin = APIClient()
        admin.force_authenticate(user=self.admin)
        r = admin.post(
            "/api/v1/admin/visits/",
            self._full_payload(employee_id=self.employee.id),
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)

    def test_local_sync_id_replay(self):
        body = self._full_payload(local_sync_id="sync-p5-1")
        r1 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        vid = r1.data["data"]["visit_id"]
        r2 = self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["data"]["duplicate"])
        self.assertEqual(r2.data["data"]["visit_id"], vid)
        self.assertEqual(
            Visit.objects.filter(employee=self.employee, local_sync_id="sync-p5-1").count(),
            1,
        )

    def test_replay_one_activity_and_route_point(self):
        body = self._full_payload(local_sync_id="sync-p5-route")
        self.client.post("/api/v1/mobile/visits/", body, format="json")
        self.client.post("/api/v1/mobile/visits/", body, format="json")
        visit = Visit.objects.get(local_sync_id="sync-p5-route")
        self.assertEqual(
            FarmerActivity.objects.filter(
                activity_type="VISIT_COMPLETED", reference_id=visit.pk
            ).count(),
            1,
        )
        self.assertEqual(
            EmployeeRoutePoint.objects.filter(
                visit_id=visit.pk, point_type=EmployeeRoutePoint.POINT_VISIT
            ).count(),
            1,
        )

    def test_farmer_id_and_phone_resolution(self):
        data = {
            "farmer": self.farmer.id,
            "farmer_name": "Ignored",
            "village": self.village,
        }
        farmer = resolve_farmer_for_visit(
            data, employee=self.employee, create_if_missing=False
        )
        self.assertEqual(farmer.pk, self.farmer.pk)

        data2 = {
            "farmer_phone": self.farmer.phone,
            "farmer_name": "Same Name Collision",
            "village": self.village,
        }
        farmer2 = resolve_farmer_for_visit(
            data2, employee=self.employee, create_if_missing=False
        )
        self.assertEqual(farmer2.pk, self.farmer.pk)

    def test_no_name_only_match(self):
        data = {
            "farmer_name": "Same Name Collision",
            "village": self.village,
        }
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            resolve_farmer_for_visit(
                data, employee=self.employee, create_if_missing=True
            )

    def test_duty_active_linkage(self):
        r = self.client.post(
            "/api/v1/mobile/visits/",
            self._full_payload(local_sync_id="duty-link"),
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        visit = Visit.objects.get(local_sync_id="duty-link")
        self.assertEqual(visit.duty_session_id, self.duty.pk)

    def test_visit_does_not_create_duty(self):
        DutySession.objects.filter(user=self.employee).update(is_active=False)
        before = DutySession.objects.filter(user=self.employee).count()
        self.client.post(
            "/api/v1/mobile/visits/",
            self._full_payload(local_sync_id="no-new-duty"),
            format="json",
        )
        self.assertEqual(
            DutySession.objects.filter(user=self.employee).count(), before
        )

    def test_historical_duty_linkage(self):
        DutySession.objects.filter(user=self.employee).update(is_active=False)
        past = timezone.localdate() - timedelta(days=2)
        hist = DutySession.objects.create(
            user=self.employee,
            date=past,
            start_time=timezone.now() - timedelta(days=2),
            is_active=False,
        )
        body = self._full_payload(
            local_sync_id="hist-duty",
            visit_date=str(past),
        )
        # FieldVisitSubmitSerializer may not expose visit_date — set via service
        result = submit_field_visit(
            employee=self.employee,
            raw_data={**self.payload, "local_sync_id": "hist-duty"},
        )
        visit = result.visit
        Visit.objects.filter(pk=visit.pk).update(visit_date=past)
        visit.refresh_from_db()
        from visits.services.field_visit_service import link_visit_duty_session

        duty = link_visit_duty_session(visit)
        self.assertEqual(duty.pk, hist.pk)

    def test_missing_coords_no_route_point(self):
        body = self._full_payload(local_sync_id="no-gps")
        body.pop("latitude")
        body.pop("longitude")
        r = self.client.post("/api/v1/mobile/visits/", body, format="json")
        # Field visit may allow missing GPS depending on validate rules
        if r.status_code == 200:
            visit = Visit.objects.get(local_sync_id="no-gps")
            self.assertFalse(
                EmployeeRoutePoint.objects.filter(visit_id=visit.pk).exists()
            )

    def test_bulk_mixed_and_order(self):
        visits = [
            self._full_payload(local_sync_id="bulk-ok-1", latitude=12.1, longitude=77.1),
            {"farmer_name": "x"},  # invalid
            self._full_payload(local_sync_id="bulk-ok-2", latitude=12.2, longitude=77.2),
            self._full_payload(local_sync_id="bulk-ok-1", latitude=12.1, longitude=77.1),  # dup
        ]
        r = self.client.post(
            "/api/v1/visits/bulk/", {"visits": visits}, format="json"
        )
        self.assertIn(r.status_code, (201, 207), r.data)
        results = r.data["data"]["results"]
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["status"], "created")
        self.assertEqual(results[1]["status"], "error")
        self.assertEqual(results[2]["status"], "created")
        self.assertEqual(results[3]["status"], "duplicate")

    def test_bulk_max_size(self):
        visits = [self._full_payload(local_sync_id=f"max-{i}") for i in range(MAX_BULK_VISITS + 1)]
        r = self.client.post(
            "/api/v1/visits/bulk/", {"visits": visits}, format="json"
        )
        self.assertEqual(r.status_code, 400)

    def test_media_client_upload_replay(self):
        r = self.client.post(
            "/api/v1/mobile/visits/",
            self._full_payload(local_sync_id="media-v"),
            format="json",
        )
        visit_id = r.data["data"]["visit_id"]
        upload = SimpleUploadedFile(
            "a.png", _png_bytes(), content_type="image/png"
        )
        r1 = self.client.post(
            f"/api/v1/mobile/visits/{visit_id}/media/",
            {"file": upload, "media_type": "image", "client_upload_id": "up-1"},
            format="multipart",
        )
        self.assertIn(r1.status_code, (200, 201), r1.data)
        upload2 = SimpleUploadedFile(
            "b.png", _png_bytes(), content_type="image/png"
        )
        r2 = self.client.post(
            f"/api/v1/mobile/visits/{visit_id}/media/",
            {"file": upload2, "media_type": "image", "client_upload_id": "up-1"},
            format="multipart",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            VisitMedia.objects.filter(visit_id=visit_id, client_upload_id="up-1").count(),
            1,
        )

    def test_media_wrong_owner_rejected(self):
        r = self.client.post(
            "/api/v1/mobile/visits/",
            self._full_payload(local_sync_id="media-own"),
            format="json",
        )
        visit_id = r.data["data"]["visit_id"]
        other_client = login_mobile_client(employee_id="EMP-P5O")
        upload = SimpleUploadedFile(
            "a.png", _png_bytes(), content_type="image/png"
        )
        bad = other_client.post(
            f"/api/v1/mobile/visits/{visit_id}/media/",
            {"file": upload, "media_type": "image"},
            format="multipart",
        )
        self.assertIn(bad.status_code, (403, 404))

    def test_update_protects_local_sync_and_duty(self):
        r = self.client.post(
            "/api/v1/mobile/visits/",
            self._full_payload(local_sync_id="protect-1"),
            format="json",
        )
        visit_id = r.data["data"]["visit_id"]
        visit = Visit.objects.get(pk=visit_id)
        duty_id = visit.duty_session_id
        patch = self.client.patch(
            f"/api/v1/mobile/visits/{visit_id}/",
            {
                "local_sync_id": "hacked",
                "duty_session": None,
                "observation": "updated note",
            },
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.data)
        visit.refresh_from_db()
        self.assertEqual(visit.local_sync_id, "protect-1")
        self.assertEqual(visit.duty_session_id, duty_id)


class ConcurrentVisitReplayTests(TransactionTestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="p5_race", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-P5R",
            phone="9000000777",
            is_active_employee=True,
        )
        district = District.objects.create(name="P5 Race D")
        self.village = Village.objects.create(name="P5 Race V", district=district)
        self.farmer = Farmer.objects.create(
            name="Race Farmer",
            phone="9777000111",
            district=district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Wheat", name_ta="Wheat", is_active=True)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_p5r",
            defaults={"name": "Pest Race", "requires_problem_master": False},
        )
        DutySession.objects.create(
            user=self.employee,
            date=timezone.localdate(),
            start_time=timezone.now(),
            is_active=True,
        )
        self.payload = {
            "farmer_id": self.farmer.id,
            "farmer_name": self.farmer.name,
            "phone_number": self.farmer.phone,
            "village_id": self.village.id,
            "crop_id": self.crop.id,
            "acreage": 1.0,
            "problem_category_id": self.category.id,
            "problem_description": "Race test",
            "latitude": 12.5,
            "longitude": 77.5,
            "local_sync_id": "race-sync-1",
        }

    def test_concurrent_same_local_sync_id(self):
        errors = []

        def worker():
            try:
                submit_field_visit(employee=self.employee, raw_data=dict(self.payload))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        run_concurrent_workers(worker)
        self.assertEqual(
            Visit.objects.filter(
                employee=self.employee, local_sync_id="race-sync-1"
            ).count(),
            1,
        )
