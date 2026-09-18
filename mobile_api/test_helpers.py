from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment
from masters.models import Taluk


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
    if village.taluk_id is None:
        district = village.district
        if district is None:
            raise ValueError("village must have district or taluk for test assignment")
        taluk, _ = Taluk.objects.get_or_create(
            name=f"TestTaluk-{village.pk}",
            district=district,
            defaults={"is_active": True},
        )
        village.taluk = taluk
        village.save()
    village.refresh_from_db()
    profile = user.employee_profile
    district = village.taluk.district
    EmployeeLocationAssignment.objects.update_or_create(
        employee=profile,
        village=village,
        defaults={
            "district": district,
            "taluk": village.taluk,
            "is_active": True,
            "is_operational": True,
        },
    )
    return village
