from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_healthz_ok(self):
        response = self.client.get(reverse("health-check"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")

    @patch("django.db.connection.cursor")
    def test_healthz_database_failure_returns_503(self, mock_cursor):
        mock_cursor.side_effect = Exception("database unavailable")
        response = self.client.get(reverse("health-check"))
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["database"], "error")
