"""Device-session enforcement on former JWT-only write endpoints."""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile


STRONG_PASSWORD = "SecurePass1!"


class DeviceSessionWriteGapTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user(
            username="gap_emp", password=STRONG_PASSWORD
        )
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="GAP-001",
            phone="9000000222",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()

    def _mobile_login(self):
        return self.client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": "GAP-001",
                "password": STRONG_PASSWORD,
                "device_id": "gap-phone",
            },
            format="json",
        )

    def _assert_session_replaced(self, method, path, data=None, **kwargs):
        login = self._mobile_login()
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        # Authenticated with JWT but without (or with revoked) device session
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        call = getattr(self.client, method)
        if data is not None:
            response = call(path, data, **kwargs)
        else:
            response = call(path, **kwargs)
        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
            msg=f"{method.upper()} {path} => {response.status_code} {getattr(response, 'data', None)}",
        )
        self.assertEqual(response.data.get("code"), "SESSION_REPLACED")

    def test_visit_bulk_requires_device_session(self):
        self._assert_session_replaced(
            "post", "/api/v1/visits/bulk/", data={"visits": []}, format="json"
        )

    def test_worklog_start_requires_device_session(self):
        self._assert_session_replaced(
            "post", "/api/v1/tracking/work/start/", data={}, format="json"
        )

    def test_notification_mark_all_requires_device_session(self):
        self._assert_session_replaced(
            "post", "/api/v1/notifications/mark-all-read/", data={}, format="json"
        )

    def test_change_password_requires_device_session(self):
        self._assert_session_replaced(
            "post",
            "/api/v1/employees/change-password/",
            data={
                "employee_id": "GAP-001",
                "current_password": STRONG_PASSWORD,
                "new_password": "NewSecure1!",
            },
            format="json",
        )

    def test_mobile_visit_form_options_requires_device_session(self):
        self._assert_session_replaced("get", "/api/v1/mobile/visit-form-options/")

    def test_farmer_put_requires_device_session(self):
        from masters.models import Farmer

        farmer = Farmer.objects.create(name="Gap Farmer", phone="9111111111")
        self._assert_session_replaced(
            "put",
            f"/api/v1/farmers/{farmer.pk}/",
            data={"name": "Updated", "phone": "9111111111"},
            format="json",
        )

    def test_revoked_session_blocked_on_visit_patch(self):
        from visits.models import Visit
        from django.utils import timezone

        login1 = self._mobile_login()
        visit = Visit.objects.create(
            employee=self.employee,
            visit_date=timezone.localdate(),
            farmer_name="X",
            farmer_phone="9000000001",
            status="completed",
        )
        # Second login revokes first session
        login2 = self._mobile_login()
        self.assertNotEqual(
            login1.data["device_session_id"], login2.data["device_session_id"]
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login1.data['access']}",
            HTTP_X_DEVICE_SESSION=login1.data["device_session_id"],
        )
        response = self.client.patch(
            f"/api/v1/visits/{visit.pk}/",
            {"observation": "should fail"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data.get("code"), "SESSION_REPLACED")
