"""Helpers for API tests that call mobile employee endpoints."""

from rest_framework.test import APIClient


def login_mobile_client(
    *,
    employee_id: str,
    password: str = "x",
    platform: str = "android",
    device_name: str = "Test Device",
) -> APIClient:
    client = APIClient()
    resp = client.post(
        "/api/v1/mobile/auth/login/",
        {
            "employee_id": employee_id,
            "password": password,
            "platform": platform,
            "device_name": device_name,
        },
        format="json",
    )
    if resp.status_code != 200:
        raise AssertionError(f"Mobile login failed: {resp.status_code} {resp.data}")
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}",
        HTTP_X_DEVICE_SESSION=resp.data["device_session_id"],
    )
    return client
