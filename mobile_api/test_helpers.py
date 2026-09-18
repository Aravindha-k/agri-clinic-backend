from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment


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


def assign_operational_territory(user, village):
    """Give a field employee operational village-level territory for tests."""
    profile = user.employee_profile
    EmployeeLocationAssignment.objects.update_or_create(
        employee=profile,
        village=village,
        defaults={
            "district_id": None,
            "taluk_id": None,
            "is_active": True,
            "is_operational": True,
        },
    )
    return village
