from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from masters.models import Crop, District, Village
from visits.models import Visit


def _make_employee(username="testworker", password="pass1234"):
    """Create a non-staff employee user."""
    return User.objects.create_user(
        username=username, password=password, is_staff=False
    )


def _get_token(client, username, password):
    r = client.post(
        "/api/v1/auth/login/",
        {"username": username, "password": password},
        format="json",
    )
    return r.data["access"]


def _seed_crop():
    return Crop.objects.create(name_en="_TestCrop", name_ta="_TestCrop", is_active=True)


def _seed_village():
    district = District.objects.create(name="_TestDistrict")
    return Village.objects.create(name="_TestVillage", district=district)


class StartVisitAPITest(TestCase):
    """Unit tests for POST /api/v1/visits/start/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_employee()
        token = _get_token(self.client, self.user.username, "pass1234")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.crop = _seed_crop()
        self.url = "/api/v1/visits/start/"
        self.base_payload = {
            "crop": self.crop.id,
            "latitude": "10.806800",
            "longitude": "78.704100",
        }

    # ─────────────────────────────────────────
    # 1. Valid request — 201 Created
    # ─────────────────────────────────────────
    def test_valid_request_returns_201(self):
        r = self.client.post(self.url, self.base_payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIn("visit_id", r.data)
        self.assertEqual(r.data["status"], "active")
        self.assertIn("start_time", r.data)

    # ─────────────────────────────────────────
    # 2. Visit saved correctly in the DB
    # ─────────────────────────────────────────
    def test_db_visit_fields_are_correct(self):
        r = self.client.post(self.url, self.base_payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        visit = Visit.objects.get(id=r.data["visit_id"])
        self.assertEqual(visit.employee, self.user)
        self.assertEqual(visit.status, "active")
        self.assertEqual(visit.crop, self.crop)
        self.assertIsNotNone(visit.visit_time)

    # ─────────────────────────────────────────
    # 3. Optional fields accepted
    # ─────────────────────────────────────────
    def test_optional_fields_accepted(self):
        village = _seed_village()
        payload = dict(
            self.base_payload,
            farmer_name="Gopal",
            village=village.id,
            notes="Test note",
        )
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        visit = Visit.objects.get(id=r.data["visit_id"])
        self.assertEqual(visit.farmer_name, "Gopal")
        self.assertEqual(visit.notes, "Test note")

    # ─────────────────────────────────────────
    # 4. Missing crop → 400
    # ─────────────────────────────────────────
    def test_missing_crop_returns_400(self):
        payload = {"latitude": "10.806800", "longitude": "78.704100"}
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self._assert_field_error(r, "crop")

    # ─────────────────────────────────────────
    # 5. Missing latitude → 400
    # ─────────────────────────────────────────
    def test_missing_latitude_returns_400(self):
        payload = {"crop": self.crop.id, "longitude": "78.704100"}
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self._assert_field_error(r, "latitude")

    # ─────────────────────────────────────────
    # 6. Missing longitude → 400
    # ─────────────────────────────────────────
    def test_missing_longitude_returns_400(self):
        payload = {"crop": self.crop.id, "latitude": "10.806800"}
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self._assert_field_error(r, "longitude")

    # ─────────────────────────────────────────
    # 7. All three required fields missing → 400 with multiple errors
    # ─────────────────────────────────────────
    def test_empty_body_returns_400_with_all_errors(self):
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        details = self._get_details(r)
        self.assertIn("crop", details)
        self.assertIn("latitude", details)
        self.assertIn("longitude", details)

    # ─────────────────────────────────────────
    # 8. Invalid (non-existent) crop ID → 400
    # ─────────────────────────────────────────
    def test_invalid_crop_id_returns_400(self):
        payload = {"crop": 99999, "latitude": "10.806800", "longitude": "78.704100"}
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self._assert_field_error(r, "crop")

    # ─────────────────────────────────────────
    # 9. Non-numeric coordinate → 400
    # ─────────────────────────────────────────
    def test_invalid_latitude_format_returns_400(self):
        payload = {
            "crop": self.crop.id,
            "latitude": "not-a-number",
            "longitude": "78.704100",
        }
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self._assert_field_error(r, "latitude")

    def test_invalid_longitude_format_returns_400(self):
        payload = {"crop": self.crop.id, "latitude": "10.806800", "longitude": "bad"}
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self._assert_field_error(r, "longitude")

    # ─────────────────────────────────────────
    # 10. Too many decimal digits → 400
    # ─────────────────────────────────────────
    def test_too_many_decimal_digits_returns_400(self):
        payload = {
            "crop": self.crop.id,
            "latitude": "10.8068000000",
            "longitude": "78.704100",
        }
        r = self.client.post(self.url, payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    # ─────────────────────────────────────────
    # 11. Unauthenticated request → 401
    # ─────────────────────────────────────────
    def test_unauthenticated_returns_401(self):
        unauth_client = APIClient()
        r = unauth_client.post(self.url, self.base_payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    # ─────────────────────────────────────────
    # 12. Wrong content-type (multipart) → 415
    # ─────────────────────────────────────────
    def test_multipart_content_type_returns_415(self):
        # APIClient multipart — no format="json"
        r = self.client.post(
            self.url,
            {"crop": self.crop.id, "latitude": "10.806800", "longitude": "78.704100"},
        )
        self.assertEqual(r.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    # ─────────────────────────────────────────
    # 13. Response envelope shape
    # ─────────────────────────────────────────
    def test_error_response_uses_standard_envelope(self):
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("success", r.data)
        self.assertFalse(r.data["success"])
        self.assertIn("error", r.data)
        self.assertIn("details", r.data["error"])

    # ─────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────
    def _get_details(self, response):
        """Pull field-level error dict regardless of envelope presence."""
        data = response.data
        if "error" in data and "details" in data["error"]:
            return data["error"]["details"]
        return data

    def _assert_field_error(self, response, field_name):
        details = self._get_details(response)
        self.assertIn(
            field_name,
            details,
            msg=f"Expected '{field_name}' in error details. Got: {details}",
        )
