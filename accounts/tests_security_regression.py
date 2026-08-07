"""Production security regression tests for authz, JWT, uploads, and GPS."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import EmployeeProfile
from masters.models import Farmer
from mobile_api.test_helpers import login_mobile_client
from tracking.models import DutySession, WorkDay
from visits.attachments import validate_attachment_payload
from visits.media_validation import MediaValidationError, validate_visit_media_file_detailed


STRONG_PASSWORD = "SecurePass1!"


def _make_employee(username: str, employee_id: str, password: str = STRONG_PASSWORD):
    user = User.objects.create_user(username=username, password=password)
    EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000001",
        is_active_employee=True,
        can_login=True,
    )
    return user


class SecurityAuthzRegressionTests(TestCase):
    def setUp(self):
        self.emp_a = _make_employee("sec_emp_a", "SEC-A")
        self.emp_b = _make_employee("sec_emp_b", "SEC-B")
        self.farmer_b = Farmer.objects.create(
            name="Farmer B",
            phone="9888888888",
            assigned_employee=self.emp_b,
            created_by_employee=self.emp_b,
            gps_location="12.971600,77.594600",
        )
        self.client_a = login_mobile_client(
            employee_id="SEC-A", password=STRONG_PASSWORD
        )

    def test_unauthenticated_employee_api_returns_401(self):
        anon = APIClient()
        resp = anon.get("/api/v1/farmers/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_employee_cannot_access_admin_tracking_api(self):
        resp = self.client_a.get("/api/admin/tracking/live/")
        self.assertIn(
            resp.status_code,
            {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN},
        )

    def test_employee_cannot_update_another_employees_farmer(self):
        resp = self.client_a.put(
            f"/api/v1/farmers/{self.farmer_b.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.farmer_b.refresh_from_db()
        self.assertEqual(self.farmer_b.name, "Farmer B")

    def test_employee_cannot_reassign_farmer_via_mass_assignment(self):
        own = Farmer.objects.create(
            name="Farmer A",
            phone="9777777777",
            assigned_employee=self.emp_a,
            created_by_employee=self.emp_a,
        )
        resp = self.client_a.put(
            f"/api/v1/farmers/{own.id}/",
            {"assigned_employee": self.emp_b.id, "name": "Farmer A2"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        own.refresh_from_db()
        self.assertEqual(own.assigned_employee_id, self.emp_a.id)
        self.assertEqual(own.name, "Farmer A2")

    def test_map_farmers_does_not_leak_unrelated_farmer_gps(self):
        resp = self.client_a.get("/api/v1/map/farmers/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        markers = resp.data.get("data") or []
        ids = {m["id"] for m in markers}
        self.assertNotIn(self.farmer_b.id, ids)

    def test_employee_cannot_create_problem_category(self):
        resp = self.client_a.post(
            "/api/v1/masters/problem-categories/",
            {"name": "HackCat", "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class SecurityJwtRegressionTests(TestCase):
    def setUp(self):
        self.emp = _make_employee("jwt_emp", "JWT-EMP")
        self.other = _make_employee("jwt_other", "JWT-OTH")
        self.client = APIClient()

    def test_invalid_access_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not.a.jwt")
        resp = self.client.get("/api/v1/farmers/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_access_token_rejected(self):
        token = AccessToken.for_user(self.emp)
        # Force expiry in the past (claim write, not relative lifetime helper).
        token.payload["exp"] = int((timezone.now() - timedelta(hours=1)).timestamp())
        token.payload["iat"] = int((timezone.now() - timedelta(hours=2)).timestamp())
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(token)}")
        resp = self.client.get("/api/v1/farmers/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_web_refresh_enforces_mobile_device_session_claim(self):
        mobile = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "JWT-EMP",
                "password": STRONG_PASSWORD,
                "device_id": "phone-1",
            },
            format="json",
        )
        self.assertEqual(mobile.status_code, status.HTTP_200_OK)
        refresh = mobile.data["refresh"]

        second = self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "JWT-EMP",
                "password": STRONG_PASSWORD,
                "device_id": "phone-2",
            },
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)

        bypass = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(bypass.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(bypass.data.get("code"), "SESSION_REPLACED")

    def test_revoked_refresh_token_rejected(self):
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "jwt_emp", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        refresh = login.data["refresh"]
        token = RefreshToken(refresh)
        token.blacklist()
        rejected = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_cannot_blacklist_foreign_refresh_token(self):
        login_a = self.client.post(
            "/api/v1/auth/login/",
            {"username": "jwt_emp", "password": STRONG_PASSWORD},
            format="json",
        )
        login_b = self.client.post(
            "/api/v1/auth/login/",
            {"username": "jwt_other", "password": STRONG_PASSWORD},
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_a.data['access']}"
        )
        self.client.post(
            "/api/v1/auth/logout/",
            {"refresh": login_b.data["refresh"]},
            format="json",
        )
        still = APIClient().post(
            "/api/v1/auth/refresh/",
            {"refresh": login_b.data["refresh"]},
            format="json",
        )
        self.assertEqual(still.status_code, status.HTTP_200_OK)

    def test_refresh_response_has_no_store_cache_control(self):
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "jwt_emp", "password": STRONG_PASSWORD},
            format="json",
        )
        refresh = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": login.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, status.HTTP_200_OK)
        self.assertIn("no-store", refresh.get("Cache-Control", "").lower())


class SecurityGpsRegressionTests(TestCase):
    def setUp(self):
        self.emp_a = _make_employee("gps_a", "GPS-A")
        self.emp_b = _make_employee("gps_b", "GPS-B")
        self.client_a = login_mobile_client(
            employee_id="GPS-A", password=STRONG_PASSWORD
        )
        now = timezone.now()
        self.workday_b = WorkDay.objects.create(
            user=self.emp_b,
            date=now.date(),
            start_time=now,
            is_active=True,
        )
        self.duty_b = DutySession.objects.create(
            user=self.emp_b,
            workday=self.workday_b,
            date=now.date(),
            start_time=now,
            is_active=True,
        )

    def test_cannot_upload_gps_for_another_employee_duty(self):
        resp = self.client_a.post(
            "/api/tracking/location/update/",
            {
                "latitude": 12.97,
                "longitude": 77.59,
                "duty_session_id": self.duty_b.id,
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertIn(resp.status_code, {400, 403, 404, 409})

    def test_invalid_lat_lng_rejected(self):
        now = timezone.now()
        workday = WorkDay.objects.create(
            user=self.emp_a,
            date=now.date(),
            start_time=now,
            is_active=True,
        )
        DutySession.objects.create(
            user=self.emp_a,
            workday=workday,
            date=now.date(),
            start_time=now,
            is_active=True,
        )
        resp = self.client_a.post(
            "/api/tracking/location/update/",
            {
                "latitude": 999,
                "longitude": 77.59,
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertIn(resp.status_code, {400, 422})

    def test_stale_duty_session_gps_rejected(self):
        start = timezone.now() - timedelta(hours=10)
        end = timezone.now() - timedelta(hours=2)
        workday = WorkDay.objects.create(
            user=self.emp_a,
            date=start.date(),
            start_time=start,
            end_time=end,
            is_active=False,
        )
        duty = DutySession.objects.create(
            user=self.emp_a,
            workday=workday,
            date=start.date(),
            start_time=start,
            end_time=end,
            is_active=False,
        )
        resp = self.client_a.post(
            "/api/tracking/location/update/",
            {
                "latitude": 12.97,
                "longitude": 77.59,
                "duty_session_id": duty.id,
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertIn(resp.status_code, {400, 403, 404, 409})


class SecurityUploadValidationTests(TestCase):
    def test_extensionless_attachment_rejected(self):
        f = SimpleUploadedFile("noext", b"abc", content_type="image/jpeg")
        errors = validate_attachment_payload(attachment_type="image", file_obj=f)
        self.assertIn("file", errors)

    def test_unsafe_svg_attachment_rejected(self):
        f = SimpleUploadedFile(
            "evil.svg", b"<svg></svg>", content_type="image/svg+xml"
        )
        errors = validate_attachment_payload(attachment_type="image", file_obj=f)
        self.assertIn("file", errors)

    def test_oversized_image_media_rejected(self):
        big = SimpleUploadedFile(
            "big.jpg",
            b"x" * (11 * 1024 * 1024),
            content_type="image/jpeg",
        )
        with self.assertRaises(MediaValidationError):
            validate_visit_media_file_detailed(media_type="image", file_obj=big)

    def test_profile_photo_svg_mime_rejected(self):
        from utils.profile_photos import validate_profile_photo

        f = SimpleUploadedFile(
            "x.jpg", b"notreally", content_type="image/svg+xml"
        )
        errors = validate_profile_photo(f)
        self.assertIn("profile_photo", errors)


@override_settings(DEBUG=False)
class SecurityMediaServingTests(TestCase):
    def test_django_does_not_mount_public_media_when_debug_false(self):
        from django.urls import resolve
        from django.urls.exceptions import Resolver404

        with self.assertRaises(Resolver404):
            resolve("/media/should-not-exist.jpg")


class SecurityLoginThrottleSmokeTests(TestCase):
    def test_login_throttling_works(self):
        from rest_framework.throttling import ScopedRateThrottle

        cache.clear()
        original = dict(ScopedRateThrottle.THROTTLE_RATES)
        ScopedRateThrottle.THROTTLE_RATES = {
            **original,
            "login": "2/minute",
        }
        try:
            client = APIClient()
            for _ in range(2):
                client.post(
                    "/api/v1/auth/login/",
                    {"username": "missing", "password": "x"},
                    format="json",
                )
            third = client.post(
                "/api/v1/auth/login/",
                {"username": "missing", "password": "x"},
                format="json",
            )
            self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        finally:
            ScopedRateThrottle.THROTTLE_RATES = original
            cache.clear()
