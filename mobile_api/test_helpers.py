from rest_framework.test import APIClient


def login_mobile_client(*, employee_id: str, password: str = "x") -> APIClient:
    client = APIClient()
    response = client.post(
        "/api/v1/mobile/auth/login/",
        {
            "employee_id": employee_id,
            "password": password,
            "device_name": "Test Phone",
            "platform": "android",
            "app_version": "1.0.0",
        },
        format="json",
    )
    token = response.data["access"]
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_DEVICE_SESSION=response.data["device_session_id"],
    )
    return client
