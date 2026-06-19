from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import EmployeeDeviceSession, EmployeeProfile
from tracking.employee_status import (
    DUTY_LOGGED_OUT,
    DUTY_OFF_DUTY,
    DUTY_ON_DUTY,
    GPS_ACTIVE,
    GPS_DELAYED,
    GPS_LOST,
    GPS_OFF,
    build_employee_status_fields,
    resolve_duty_status,
    resolve_gps_status,
)
from tracking.gps_state import (
    PERMISSION_DENIED,
    PERMISSION_SERVICES_DISABLED,
    is_mobile_gps_off,
    upsert_employee_gps_state,
)
from tracking.models import (
    AvailabilityEvent,
    DutySession,
    EmployeeGpsState,
    EmployeeLiveLocation,
    WorkDay,
)


class EmployeeStatusRulesTest(TestCase):
    def test_duty_status_rules(self):
        self.assertEqual(
            resolve_duty_status(has_active_duty=True, has_active_device_session=True),
            DUTY_ON_DUTY,
        )
        self.assertEqual(
            resolve_duty_status(has_active_duty=False, has_active_device_session=True),
            DUTY_OFF_DUTY,
        )
        self.assertEqual(
            resolve_duty_status(has_active_duty=False, has_active_device_session=False),
            DUTY_LOGGED_OUT,
        )

    def test_gps_status_active(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(last_gps_at=now - timedelta(minutes=2), now=now),
            GPS_ACTIVE,
        )

    def test_gps_status_delayed(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(last_gps_at=now - timedelta(minutes=5), now=now),
            GPS_DELAYED,
        )

    def test_gps_status_lost(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(last_gps_at=now - timedelta(minutes=15), now=now),
            GPS_LOST,
        )

    def test_gps_off_when_gps_enabled_false(self):
        now = timezone.now()
        self.assertTrue(is_mobile_gps_off(gps_enabled=False))
        self.assertEqual(
            resolve_gps_status(
                last_gps_at=now,
                gps_enabled=False,
                latitude=12.97,
                longitude=77.59,
                now=now,
            ),
            GPS_OFF,
        )

    def test_gps_off_when_permission_denied(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(
                last_gps_at=now,
                location_permission_status=PERMISSION_DENIED,
                latitude=12.97,
                longitude=77.59,
                now=now,
            ),
            GPS_OFF,
        )

    def test_gps_off_when_services_disabled(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(
                last_gps_at=now,
                location_permission_status=PERMISSION_SERVICES_DISABLED,
                latitude=12.97,
                longitude=77.59,
                now=now,
            ),
            GPS_OFF,
        )

    def test_invalid_coordinates_are_gps_off(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(
                last_gps_at=now,
                latitude=999,
                longitude=77.59,
                now=now,
            ),
            GPS_OFF,
        )

    def test_legacy_availability_event_fallback(self):
        now = timezone.now()
        self.assertEqual(
            resolve_gps_status(last_gps_at=now, gps_off=True, now=now),
            GPS_OFF,
        )

    def test_legacy_fields_preserved(self):
        now = timezone.now()
        fields = build_employee_status_fields(
            has_active_duty=True,
            has_active_device_session=True,
            last_gps_at=now - timedelta(minutes=1),
            latitude=12.97,
            longitude=77.59,
            gps_enabled=True,
            location_permission_status="granted",
            background_tracking_enabled=True,
            now=now,
        )
        self.assertEqual(fields["duty_status"], DUTY_ON_DUTY)
        self.assertEqual(fields["gps_status"], GPS_ACTIVE)
        self.assertTrue(fields["gps_enabled"])
        self.assertEqual(fields["location_permission_status"], "granted")
        self.assertTrue(fields["background_tracking_enabled"])
        self.assertEqual(fields["connection"], "ONLINE")
        self.assertEqual(fields["gps_signal"], "GPS_ON")
        self.assertEqual(fields["legacy_gps_status"], "GPS_ON")
        self.assertTrue(fields["is_on_duty"])
        self.assertEqual(fields["last_seen_minutes"], 1)


class EmployeeStatusAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="st_admin",
            password="x",
            is_staff=True,
        )
        self.employee = User.objects.create_user(username="st_emp", password="secret123")
        self.profile = EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="ST-001",
            phone="9000000666",
            is_active_employee=True,
        )
        self.today = timezone.localdate()
        self.client = APIClient()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self._auth_employee()

    def _auth_employee(self):
        r = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "ST-001",
                "password": "secret123",
                "device_name": "Test Phone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {r.data['access']}",
            HTTP_X_DEVICE_SESSION=r.data["device_session_id"],
        )

    def _start_duty(self):
        self.client.post(
            "/api/tracking/duty/start/",
            {"latitude": 12.9716, "longitude": 77.5946},
            format="json",
        )

    def _location_update(self, **extra):
        payload = {
            "latitude": 12.9716,
            "longitude": 77.5946,
            "gps_enabled": True,
            "location_permission_status": "granted",
            "background_tracking_enabled": True,
            **extra,
        }
        return self.client.post(
            "/api/tracking/location/update/",
            payload,
            format="json",
        )

    def _live_row(self):
        r = self.admin_client.get("/api/admin/tracking/live/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        return next(
            e for e in r.data["data"]["employees"] if e["user_id"] == self.employee.id
        )

    def test_location_update_stores_mobile_gps_state(self):
        self._start_duty()
        self._location_update()
        state = EmployeeGpsState.objects.get(user=self.employee)
        self.assertTrue(state.gps_enabled)
        self.assertEqual(state.location_permission_status, "granted")
        self.assertTrue(state.background_tracking_enabled)
        live = EmployeeLiveLocation.objects.get(user=self.employee)
        self.assertTrue(live.gps_enabled)
        self.assertEqual(live.location_permission_status, "granted")

    def test_live_api_gps_active(self):
        self._start_duty()
        self._location_update()
        row = self._live_row()
        self.assertEqual(row["duty_status"], DUTY_ON_DUTY)
        self.assertEqual(row["gps_status"], GPS_ACTIVE)
        self.assertTrue(row["gps_enabled"])
        self.assertEqual(row["legacy_gps_status"], "GPS_ON")

    def test_live_api_gps_delayed(self):
        self._start_duty()
        t0 = timezone.now() - timedelta(minutes=5)
        self._location_update(recorded_at=t0.isoformat())
        row = self._live_row()
        self.assertEqual(row["gps_status"], GPS_DELAYED)

    def test_live_api_gps_lost(self):
        self._start_duty()
        t0 = timezone.now() - timedelta(minutes=20)
        self._location_update(recorded_at=t0.isoformat())
        row = self._live_row()
        self.assertEqual(row["gps_status"], GPS_LOST)
        self.assertEqual(row["connection"], "OFFLINE")

    def test_live_api_gps_off_permission_denied(self):
        self._start_duty()
        self._location_update(
            location_permission_status=PERMISSION_DENIED,
            gps_enabled=False,
        )
        row = self._live_row()
        self.assertEqual(row["gps_status"], GPS_OFF)
        self.assertEqual(row["location_permission_status"], PERMISSION_DENIED)
        self.assertEqual(row["legacy_gps_status"], "GPS_OFF")

    def test_live_api_gps_off_services_disabled(self):
        self._start_duty()
        self._location_update(
            location_permission_status=PERMISSION_SERVICES_DISABLED,
            gps_enabled=True,
        )
        row = self._live_row()
        self.assertEqual(row["gps_status"], GPS_OFF)
        self.assertEqual(row["location_permission_status"], PERMISSION_SERVICES_DISABLED)

    def test_heartbeat_stores_gps_state(self):
        self._start_duty()
        r = self.client.post(
            "/api/tracking/heartbeat/",
            {
                "gps_enabled": False,
                "location_permission_status": PERMISSION_DENIED,
                "background_tracking_enabled": False,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        state = EmployeeGpsState.objects.get(user=self.employee)
        self.assertFalse(state.gps_enabled)
        self.assertEqual(state.location_permission_status, PERMISSION_DENIED)

    def test_bulk_location_carries_request_level_gps_state(self):
        self._start_duty()
        t0 = timezone.now()
        r = self.client.post(
            "/api/tracking/location/bulk/",
            {
                "gps_enabled": False,
                "location_permission_status": PERMISSION_DENIED,
                "background_tracking_enabled": False,
                "locations": [
                    {
                        "latitude": 12.9716,
                        "longitude": 77.5946,
                        "captured_at": t0.isoformat(),
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        state = EmployeeGpsState.objects.get(user=self.employee)
        self.assertFalse(state.gps_enabled)
        row = self._live_row()
        self.assertEqual(row["gps_status"], GPS_OFF)

    def test_off_duty_logged_in_status(self):
        EmployeeLiveLocation.objects.create(
            user=self.employee,
            latitude=12.9716,
            longitude=77.5946,
            recorded_at=timezone.now() - timedelta(hours=1),
        )
        row = self._live_row()
        self.assertEqual(row["duty_status"], DUTY_OFF_DUTY)
        self.assertEqual(row["gps_status"], GPS_LOST)

    def test_logged_out_status_on_day_summary(self):
        EmployeeDeviceSession.objects.filter(user=self.employee).update(is_active=False)
        url = f"/api/admin/employees/{self.profile.pk}/day-summary/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["duty_status"], DUTY_LOGGED_OUT)
        self.assertEqual(data["gps_status"], GPS_OFF)
        self.assertFalse(data["is_on_duty"])

    def test_day_report_includes_gps_state_fields(self):
        self._start_duty()
        self._location_update()
        url = f"/api/admin/employees/{self.profile.pk}/day-report/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data["data"]
        self.assertEqual(data["duty_status"], DUTY_ON_DUTY)
        self.assertEqual(data["gps_status"], GPS_ACTIVE)
        self.assertIn("gps_enabled", data)
        self.assertIn("location_permission_status", data)
        self.assertIn("background_tracking_enabled", data)
        self.assertEqual(data["status"]["gps_status"], GPS_ACTIVE)

    def test_legacy_availability_event_when_mobile_state_missing(self):
        self._start_duty()
        self.client.post(
            "/api/tracking/location/update/",
            {"latitude": 12.9716, "longitude": 77.5946},
            format="json",
        )
        EmployeeGpsState.objects.filter(user=self.employee).delete()
        EmployeeLiveLocation.objects.filter(user=self.employee).update(
            gps_enabled=None,
            location_permission_status=None,
            background_tracking_enabled=None,
            gps_reported_at=None,
        )
        workday = WorkDay.objects.get(user=self.employee, is_active=True)
        AvailabilityEvent.objects.create(
            user=self.employee,
            workday=workday,
            event_type="GPS_OFF",
            start_time=timezone.now(),
        )
        url = f"/api/admin/employees/{self.profile.pk}/day-summary/"
        r = self.admin_client.get(url, {"date": str(self.today)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["gps_status"], GPS_OFF)

    def test_upsert_employee_gps_state_helper(self):
        upsert_employee_gps_state(
            self.employee,
            {
                "gps_enabled": True,
                "location_permission_status": "granted",
                "background_tracking_enabled": False,
            },
        )
        state = EmployeeGpsState.objects.get(user=self.employee)
        self.assertFalse(state.background_tracking_enabled)
