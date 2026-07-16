"""Phase 6 — duty day-map API tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from mobile_api.tests.helpers import login_mobile_client
from tracking.day_map_service import (
    ROUTE_SOURCE_CANONICAL,
    ROUTE_SOURCE_LEGACY,
    SOURCE_DUTY_START,
    SOURCE_EARLIEST_FALLBACK,
    SOURCE_LAST_FALLBACK,
    SOURCE_WORKDAY_START,
    build_duty_day_map,
)
from tracking.models import DutySession, EmployeeRoutePoint, LocationLog, WorkDay
from visits.models import Visit
from visits.services.field_visit_service import submit_field_visit


class DutyDayMapTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="p6_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-P6",
            phone="9000000666",
            is_active_employee=True,
        )
        self.other = User.objects.create_user(username="p6_other", password="x")
        EmployeeProfile.objects.create(
            user=self.other,
            employee_id="EMP-P6O",
            phone="9000000667",
            is_active_employee=True,
        )
        self.admin = User.objects.create_user(
            username="p6_admin", password="x", is_staff=True, is_superuser=True
        )
        self.district = District.objects.create(name="P6 Dist")
        self.village = Village.objects.create(name="P6 Vil", district=self.district)
        self.farmer = Farmer.objects.create(
            name="P6 Farmer",
            phone="9888000666",
            district=self.district,
            village=self.village,
        )
        self.crop = Crop.objects.create(name_en="Cotton", name_ta="Cotton", is_active=True)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_p6",
            defaults={"name": "Pest P6", "requires_problem_master": False},
        )
        now = timezone.now()
        self.duty = DutySession.objects.create(
            user=self.employee,
            date=timezone.localdate(),
            start_time=now,
            is_active=True,
            latitude=Decimal("12.970000"),
            longitude=Decimal("77.590000"),
        )
        self.client = login_mobile_client(employee_id="EMP-P6")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def _add_route(self, *, lat, lng, point_type="gps", visit_id=None, minutes=0):
        return EmployeeRoutePoint.objects.create(
            user=self.employee,
            duty_session=self.duty,
            latitude=Decimal(str(lat)),
            longitude=Decimal(str(lng)),
            recorded_at=timezone.now() + timedelta(minutes=minutes),
            point_type=point_type,
            visit_id=visit_id,
            is_permanent=point_type == "visit",
        )

    def test_empty_duty_map(self):
        duty = DutySession.objects.create(
            user=self.employee,
            date=timezone.localdate() - timedelta(days=3),
            start_time=timezone.now() - timedelta(days=3),
            end_time=timezone.now() - timedelta(days=3) + timedelta(hours=1),
            is_active=False,
            completion_reason="MANUAL",
        )
        # No start coords
        data = build_duty_day_map(duty, include_live_location=False)
        self.assertEqual(data["visit_markers"], [])
        self.assertEqual(data["route_points"], [])
        self.assertIsNone(data["start_marker"])
        self.assertIsNone(data["end_marker"])
        self.assertIsNone(data["map_bounds"]["center_latitude"])

    def test_active_duty_endpoint_and_start_marker(self):
        self._add_route(lat=12.971, lng=77.591, minutes=5)
        r = self.client.get(f"/api/v1/tracking/duty/{self.duty.pk}/map/")
        self.assertEqual(r.status_code, 200, r.data)
        data = r.data["data"]
        self.assertEqual(data["duty"]["id"], self.duty.pk)
        # Explicit WORKDAY_START route point preferred when present; else DUTY_START coords.
        self.assertIn(
            data["start_marker"]["source"],
            {SOURCE_DUTY_START, SOURCE_WORKDAY_START},
        )
        self.assertIsNone(data["end_marker"])
        self.assertEqual(data["metadata"]["route_source"], ROUTE_SOURCE_CANONICAL)

    def test_current_map_convenience(self):
        r = self.client.get("/api/v1/tracking/duty/current/map/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["data"]["duty"]["id"], self.duty.pk)

    def test_employee_cannot_see_other_duty(self):
        other_duty = DutySession.objects.create(
            user=self.other,
            date=timezone.localdate(),
            start_time=timezone.now(),
            is_active=True,
        )
        r = self.client.get(f"/api/v1/tracking/duty/{other_duty.pk}/map/")
        self.assertEqual(r.status_code, 404)

    def test_admin_can_view_employee_duty(self):
        r = self.admin_client.get(f"/api/v1/tracking/duty/{self.duty.pk}/map/")
        self.assertEqual(r.status_code, 200, r.data)

    def test_completed_duty_end_marker_inferred(self):
        self._add_route(lat=12.971, lng=77.591, minutes=1)
        self._add_route(lat=12.972, lng=77.592, minutes=10)
        self.duty.is_active = False
        self.duty.end_time = timezone.now()
        self.duty.completion_reason = "MANUAL"
        self.duty.save()
        data = build_duty_day_map(self.duty, include_live_location=False)
        self.assertIsNotNone(data["end_marker"])
        self.assertEqual(data["end_marker"]["source"], SOURCE_LAST_FALLBACK)
        self.assertTrue(data["end_marker"]["inferred"])

    def test_active_duty_no_inferred_end(self):
        self._add_route(lat=12.971, lng=77.591)
        data = build_duty_day_map(self.duty, include_live_location=False)
        self.assertIsNone(data["end_marker"])

    def test_visit_one_marker_no_duplicate(self):
        result = submit_field_visit(
            employee=self.employee,
            raw_data={
                "farmer_id": self.farmer.id,
                "farmer_name": self.farmer.name,
                "phone_number": self.farmer.phone,
                "village_id": self.village.id,
                "crop_id": self.crop.id,
                "acreage": 1.0,
                "problem_category_id": self.category.id,
                "problem_description": "P6 issue",
                "latitude": 12.973,
                "longitude": 77.593,
                "local_sync_id": "p6-visit-1",
            },
        )
        visit = result.visit
        Visit.objects.filter(pk=visit.pk).update(duty_session=self.duty)
        visit.refresh_from_db()
        # Ensure VISIT route point on this duty
        EmployeeRoutePoint.objects.filter(visit_id=visit.pk).update(
            duty_session=self.duty, user=self.employee
        )
        if not EmployeeRoutePoint.objects.filter(
            visit_id=visit.pk, point_type=EmployeeRoutePoint.POINT_VISIT
        ).exists():
            self._add_route(
                lat=12.973, lng=77.593, point_type="visit", visit_id=visit.pk, minutes=3
            )

        data = build_duty_day_map(self.duty, include_live_location=False)
        markers = [m for m in data["visit_markers"] if m["visit_id"] == visit.pk]
        self.assertEqual(len(markers), 1)
        # Route may include the visit point, but markers stay singular
        visit_route_pts = [
            p for p in data["route_points"] if p.get("visit_id") == visit.pk
        ]
        self.assertLessEqual(len(visit_route_pts), 1)

    def test_invalid_route_point_skipped(self):
        self._add_route(lat=12.971, lng=77.591)
        # Simulate invalid by patching validation path with a mocked row
        from tracking import day_map_service as dms
        from unittest import mock

        real_serialize = dms._serialize_route_rows

        def wrap(points, *, invalid_skipped):
            # Inject a fake invalid before serialize by appending a bogus ORM-like object
            class Bad:
                pk = -1
                id = -1
                latitude = 999
                longitude = 77
                accuracy = None
                recorded_at = timezone.now()
                created_at = timezone.now()
                point_type = "gps"
                client_point_id = None
                visit_id = None
                duty_session_id = self.duty.pk

            return real_serialize(list(points) + [Bad()], invalid_skipped=invalid_skipped)

        with mock.patch.object(dms, "_serialize_route_rows", side_effect=wrap):
            with mock.patch.object(
                dms,
                "_load_canonical_route_points",
                return_value=list(
                    EmployeeRoutePoint.objects.filter(duty_session=self.duty)
                ),
            ):
                data = dms.build_duty_day_map(self.duty, include_live_location=False)
        self.assertGreaterEqual(data["summary"]["invalid_points_skipped"], 1)
        self.assertTrue(all(p["id"] != -1 for p in data["route_points"]))

    def test_bounds_and_distance(self):
        self._add_route(lat=12.970, lng=77.590, minutes=0)
        self._add_route(lat=12.980, lng=77.600, minutes=5)
        data = build_duty_day_map(self.duty, include_live_location=False)
        bounds = data["map_bounds"]
        self.assertIsNotNone(bounds["min_latitude"])
        self.assertGreaterEqual(bounds["max_latitude"], bounds["min_latitude"])
        self.assertIsNotNone(data["summary"]["distance_meters"])
        self.assertEqual(data["summary"]["distance_source"], "HAVERSINE")

    def test_legacy_fallback_when_no_route_points(self):
        workday = WorkDay.objects.create(
            user=self.employee,
            date=self.duty.date,
            start_time=self.duty.start_time,
            is_active=True,
        )
        self.duty.workday = workday
        self.duty.save(update_fields=["workday"])
        LocationLog.objects.create(
            user=self.employee,
            workday=workday,
            latitude=Decimal("12.975000"),
            longitude=Decimal("77.595000"),
            recorded_at=timezone.now(),
        )
        data = build_duty_day_map(self.duty, include_live_location=False)
        self.assertEqual(data["metadata"]["route_source"], ROUTE_SOURCE_LEGACY)
        self.assertEqual(len(data["route_points"]), 1)
        self.assertEqual(data["route_points"][0]["source"], "LEGACY_LOCATION_LOG")

    def test_sampling_metadata(self):
        # Create just over limit would be slow; unit-test sampler via monkeypatch size
        from tracking import day_map_service as dms

        points = [
            {
                "id": i,
                "latitude": 12.0 + i * 0.001,
                "longitude": 77.0,
                "source": "FOREGROUND_TRACKING",
                "visit_id": None,
                "sequence": i,
            }
            for i in range(20)
        ]
        points[0]["source"] = "WORKDAY_START"
        points[-1]["source"] = "WORKDAY_END"
        sampled, was_sampled = dms._sample_route_points(points, limit=5)
        self.assertTrue(was_sampled)
        self.assertLessEqual(len(sampled), 5)
        sources = {p["source"] for p in sampled}
        self.assertIn("WORKDAY_START", sources)
        self.assertIn("WORKDAY_END", sources)

    def test_admin_compat_wrapper(self):
        self._add_route(lat=12.971, lng=77.591)
        r = self.admin_client.get(
            f"/api/admin/tracking/employee/{self.employee.id}/today-route/"
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("day_map", r.data["data"])
        self.assertEqual(r.data["data"]["duty_session_id"], self.duty.pk)

    def test_query_count_bounded(self):
        for i in range(15):
            self._add_route(
                lat=12.97 + i * 0.001, lng=77.59 + i * 0.001, minutes=i
            )
        with CaptureQueriesContext(connection) as ctx:
            build_duty_day_map(self.duty, include_live_location=False)
        # Should not N+1 per point (allow timer/expiry overhead)
        self.assertLess(len(ctx), 25)

    def test_earliest_fallback_start_without_duty_coords(self):
        self.duty.latitude = None
        self.duty.longitude = None
        self.duty.save(update_fields=["latitude", "longitude"])
        self._add_route(lat=12.971, lng=77.591, minutes=1)
        data = build_duty_day_map(self.duty, include_live_location=False)
        self.assertEqual(data["start_marker"]["source"], SOURCE_EARLIEST_FALLBACK)
        self.assertTrue(data["start_marker"]["inferred"])

    def test_invalid_visit_coords_skipped(self):
        visit = Visit.objects.create(
            employee=self.employee,
            duty_session=self.duty,
            visit_date=timezone.localdate(),
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            village=self.village,
            crop=self.crop,
            problem_category=self.category,
            problem_description="bad coords",
            land_area=1.0,
            latitude=95.0,
            longitude=77.0,
            status="completed",
        )
        data = build_duty_day_map(self.duty, include_live_location=False)
        ids = {m["visit_id"] for m in data["visit_markers"]}
        self.assertNotIn(visit.pk, ids)
        self.assertGreaterEqual(data["summary"]["invalid_points_skipped"], 1)


class DutyDayMapSessionTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="p6_sess", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-P6S",
            phone="9000000688",
            is_active_employee=True,
        )
        self.duty = DutySession.objects.create(
            user=self.employee,
            date=timezone.localdate(),
            start_time=timezone.now(),
            is_active=True,
            latitude=Decimal("12.970000"),
            longitude=Decimal("77.590000"),
        )
        self.client = login_mobile_client(employee_id="EMP-P6S")

    def test_replaced_session_rejected(self):
        # Second login replaces the first device session
        login_mobile_client(employee_id="EMP-P6S", device_name="Other Phone")
        r = self.client.get(f"/api/v1/tracking/duty/{self.duty.pk}/map/")
        self.assertEqual(r.status_code, 409)
