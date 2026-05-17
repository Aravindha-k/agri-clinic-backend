from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from masters.models import Crop
from visits.models import Visit


class DeprecatedVisitFlowAPITest(TestCase):
    """Draft start/active/complete visit endpoints are removed."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="flow_user", password="x")
        self.client.force_authenticate(user=self.user)
        self.crop = Crop.objects.create(name_en="Test", name_ta="Test", is_active=True)

    def test_start_visit_returns_410_without_db_row(self):
        before = Visit.objects.count()
        r = self.client.post(
            "/api/v1/visits/start/",
            {"crop": self.crop.id, "latitude": "10.0", "longitude": "78.0"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_410_GONE)
        self.assertFalse(r.data["success"])
        self.assertEqual(Visit.objects.count(), before)

    def test_active_visit_returns_410(self):
        r = self.client.get("/api/v1/visits/active/")
        self.assertEqual(r.status_code, status.HTTP_410_GONE)

    def test_complete_visit_returns_410(self):
        r = self.client.post("/api/v1/visits/1/complete/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_410_GONE)
