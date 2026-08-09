"""Farmer detail PATCH/DELETE authorization for staff admin vs employees."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import EmployeeProfile
from masters.models import Farmer, FarmerField
from mobile_api.test_helpers import login_mobile_client
from visits.models import Visit


STRONG_PASSWORD = "SecurePass1!"


def _auth(user: User) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def _make_owner():
    user = User.objects.create_user(
        username="owner.farmer.crud",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=True,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="OWN-FCR",
        phone="9111000001",
        is_active_employee=True,
        can_login=True,
    )
    return user


def _make_staff_admin():
    user = User.objects.create_user(
        username="staff.farmer.crud",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="ADM-FCR",
        phone="9111000002",
        is_active_employee=True,
        can_login=True,
        role="admin",
    )
    return user


def _make_employee():
    user = User.objects.create_user(
        username="emp.farmer.crud",
        password=STRONG_PASSWORD,
        is_staff=False,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="EMP-FCR",
        phone="9111000003",
        is_active_employee=True,
        can_login=True,
    )
    return user


class FarmerDetailMutationTests(TestCase):
    def setUp(self):
        self.owner = _make_owner()
        self.staff = _make_staff_admin()
        self.employee = _make_employee()
        self.owner_client = _auth(self.owner)
        self.staff_client = _auth(self.staff)
        self.emp_client = login_mobile_client(
            employee_id="EMP-FCR", password=STRONG_PASSWORD
        )
        self.anon = APIClient()

        self.farmer = Farmer.objects.create(
            name="Mutation Farmer",
            phone="9222000001",
            assigned_employee=self.employee,
            created_by_employee=self.employee,
        )

    def test_anonymous_get_and_mutate_401(self):
        url = f"/api/v1/farmers/{self.farmer.id}/"
        self.assertEqual(self.anon.get(url).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            self.anon.patch(url, {"name": "X"}, format="json").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(
            self.anon.delete(url).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_staff_admin_get_patch_put_and_db_persists(self):
        url = f"/api/v1/farmers/{self.farmer.id}/"
        get_r = self.staff_client.get(url)
        self.assertEqual(get_r.status_code, status.HTTP_200_OK)

        patch_r = self.staff_client.patch(
            url, {"name": "Staff Patched Name"}, format="json"
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.name, "Staff Patched Name")

        put_r = self.staff_client.put(
            url, {"name": "Staff Put Name", "phone": "9222000001"}, format="json"
        )
        self.assertEqual(put_r.status_code, status.HTTP_200_OK)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.name, "Staff Put Name")

    def test_owner_patch_persists(self):
        url = f"/api/v1/farmers/{self.farmer.id}/"
        r = self.owner_client.patch(url, {"name": "Owner Patched"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.name, "Owner Patched")

    def test_field_employee_cannot_update_unrelated_farmer(self):
        other = Farmer.objects.create(
            name="Other Farmer",
            phone="9222000099",
        )
        url = f"/api/v1/farmers/{other.id}/"
        # Detail may 404 if scoped out, or 403 if visible but not writable.
        r = self.emp_client.patch(url, {"name": "Hijack"}, format="json")
        self.assertIn(
            r.status_code,
            {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND},
        )
        other.refresh_from_db()
        self.assertEqual(other.name, "Other Farmer")

    def test_staff_admin_hard_deletes_clean_farmer(self):
        target = Farmer.objects.create(name="Delete Me", phone="9222000011")
        url = f"/api/v1/farmers/{target.id}/"
        r = self.staff_client.delete(url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(Farmer.objects.filter(pk=target.id).exists())

    def test_owner_hard_deletes_farmer_with_visit_set_null(self):
        target = Farmer.objects.create(name="Delete With Visit", phone="9222000012")
        visit = Visit.objects.create(
            employee=self.employee,
            farmer=target,
            farmer_name=target.name,
            farmer_phone=target.phone,
            latitude=12.9,
            longitude=77.5,
            notes="keep history",
        )
        FarmerField.objects.create(
            farmer=target, land_name="Temp Field", created_by_employee=self.employee
        )
        url = f"/api/v1/farmers/{target.id}/"
        r = self.owner_client.delete(url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(Farmer.objects.filter(pk=target.id).exists())
        visit.refresh_from_db()
        self.assertIsNone(visit.farmer_id)
        self.assertEqual(visit.farmer_name, "Delete With Visit")
        self.assertFalse(FarmerField.objects.filter(farmer_id=target.id).exists())

    def test_field_employee_cannot_delete(self):
        url = f"/api/v1/farmers/{self.farmer.id}/"
        r = self.emp_client.delete(url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.id).exists())

    def test_admin_viewset_path_also_supports_patch_delete(self):
        """/api/v1/admin/farmers/{id}/ remains full CRUD for staff."""
        target = Farmer.objects.create(name="Admin Path", phone="9222000013")
        url = f"/api/v1/admin/farmers/{target.id}/"
        patch_r = self.staff_client.patch(
            url, {"name": "Admin Path Updated"}, format="json"
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)
        del_r = self.staff_client.delete(url)
        self.assertEqual(del_r.status_code, status.HTTP_200_OK)
        self.assertFalse(Farmer.objects.filter(pk=target.id).exists())
