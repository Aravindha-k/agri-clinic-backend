"""Regression: staff admin (kac.admin-like) can CRUD operational Admin APIs."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    CropIssue,
    District,
    Farmer,
    FarmerField,
    ProblemCategory,
    Recommendation,
    Village,
)
from visits.models import Visit


STRONG_PASSWORD = "SecurePass1!"


def _auth_client(user: User) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def _make_owner():
    user = User.objects.create_user(
        username="kac.owner.test",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=True,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="OWN-TEST",
        phone="9000000001",
        is_active_employee=True,
        can_login=True,
        role="admin",
    )
    return user


def _make_staff_admin():
    user = User.objects.create_user(
        username="kac.admin.test",
        password=STRONG_PASSWORD,
        is_staff=True,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="ADM-TEST",
        phone="9000000002",
        is_active_employee=True,
        can_login=True,
        role="admin",
    )
    return user


def _make_field_employee():
    user = User.objects.create_user(
        username="field.emp.test",
        password=STRONG_PASSWORD,
        is_staff=False,
        is_superuser=False,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="FLD-TEST",
        phone="9000000003",
        is_active_employee=True,
        can_login=True,
    )
    return user


class StaffAdminCrudRegressionTests(TestCase):
    def setUp(self):
        self.owner = _make_owner()
        self.staff_admin = _make_staff_admin()
        self.employee = _make_field_employee()
        self.owner_client = _auth_client(self.owner)
        self.admin_client = _auth_client(self.staff_admin)
        self.emp_client = _auth_client(self.employee)
        self.anon = APIClient()

        self.district = District.objects.create(name="Admin CRUD District")
        self.village = Village.objects.create(
            name="Admin CRUD Village", district=self.district
        )
        self.crop = Crop.objects.create(
            name_en="Paddy", name_ta="Paddy", is_active=True
        )
        self.farmer = Farmer.objects.create(
            name="CRUD Farmer",
            phone="9111000001",
            district=self.district,
            village=self.village,
            assigned_employee=self.employee,
        )
        self.field = FarmerField.objects.create(
            farmer=self.farmer,
            land_name="North Field",
            land_size="1.50",
            created_by_employee=self.employee,
        )
        self.visit = Visit.objects.create(
            employee=self.employee,
            farmer=self.farmer,
            farmer_name=self.farmer.name,
            farmer_phone=self.farmer.phone,
            district=self.district,
            village=self.village,
            crop=self.crop,
            field=self.field,
            latitude=12.97,
            longitude=77.59,
            notes="baseline visit",
        )
        self.issue = CropIssue.objects.create(
            visit=self.visit,
            crop=self.crop,
            severity="medium",
            status="open",
            description="Leaf spot",
        )
        self.recommendation = Recommendation.objects.create(
            issue=self.issue,
            given_by=self.employee,
            fertilizer="NPK",
            notes="apply weekly",
        )
        self.problem_category = ProblemCategory.objects.create(
            name="CRUD Pest", code="crud_pest_test", is_active=True
        )

    def test_anonymous_admin_apis_return_401(self):
        paths = [
            "/api/v1/admin/farmers/",
            "/api/v1/admin/visits/",
            "/api/v1/admin/issues/",
            "/api/v1/admin/crop-catalog/",
            "/api/v1/employees/admin/employees/",
            "/api/v1/masters/districts/",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(
                    self.anon.get(path).status_code,
                    status.HTTP_401_UNAUTHORIZED,
                )

    def test_field_employee_forbidden_from_admin_crud(self):
        paths = [
            "/api/v1/admin/farmers/",
            "/api/v1/admin/visits/",
            "/api/v1/employees/admin/employees/",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(
                    self.emp_client.get(path).status_code,
                    status.HTTP_403_FORBIDDEN,
                )

    def test_staff_admin_farmer_crud(self):
        list_r = self.admin_client.get("/api/v1/admin/farmers/")
        self.assertEqual(list_r.status_code, status.HTTP_200_OK)

        detail_r = self.admin_client.get(f"/api/v1/admin/farmers/{self.farmer.id}/")
        self.assertEqual(detail_r.status_code, status.HTTP_200_OK)

        create_r = self.admin_client.post(
            "/api/v1/admin/farmers/",
            {
                "name": "Admin Created Farmer",
                "phone": "9111000099",
                "district": self.district.id,
                "village": self.village.id,
            },
            format="json",
        )
        self.assertEqual(create_r.status_code, status.HTTP_201_CREATED)
        created_id = create_r.data["id"]

        patch_r = self.admin_client.patch(
            f"/api/v1/admin/farmers/{created_id}/",
            {"name": "Admin Updated Farmer"},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)

        delete_r = self.admin_client.delete(f"/api/v1/admin/farmers/{created_id}/")
        self.assertEqual(delete_r.status_code, status.HTTP_200_OK)
        self.assertFalse(Farmer.objects.filter(pk=created_id).exists())

    def test_owner_farmer_crud_still_works(self):
        r = self.owner_client.get("/api/v1/admin/farmers/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        create_r = self.owner_client.post(
            "/api/v1/admin/farmers/",
            {"name": "Owner Farmer", "phone": "9111000088"},
            format="json",
        )
        self.assertEqual(create_r.status_code, status.HTTP_201_CREATED)

    def test_staff_admin_field_crud(self):
        list_r = self.admin_client.get("/api/v1/admin/fields/")
        self.assertEqual(list_r.status_code, status.HTTP_200_OK)

        create_r = self.admin_client.post(
            "/api/v1/admin/fields/",
            {
                "farmer": self.farmer.id,
                "land_name": "Admin Field",
                "land_size": "2.00",
            },
            format="json",
        )
        self.assertEqual(create_r.status_code, status.HTTP_201_CREATED)
        field_id = create_r.data["id"]

        patch_r = self.admin_client.patch(
            f"/api/v1/admin/fields/{field_id}/",
            {"land_name": "Admin Field Updated"},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)

        delete_r = self.admin_client.delete(f"/api/v1/admin/fields/{field_id}/")
        self.assertIn(
            delete_r.status_code,
            {status.HTTP_200_OK, status.HTTP_204_NO_CONTENT},
        )

    def test_staff_admin_visit_list_detail_update_delete(self):
        list_r = self.admin_client.get("/api/v1/admin/visits/")
        self.assertEqual(list_r.status_code, status.HTTP_200_OK)

        detail_r = self.admin_client.get(f"/api/v1/admin/visits/{self.visit.id}/")
        self.assertEqual(detail_r.status_code, status.HTTP_200_OK)

        patch_r = self.admin_client.patch(
            f"/api/v1/admin/visits/{self.visit.id}/",
            {"notes": "updated by staff admin"},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.notes, "updated by staff admin")

        # Create under a dedicated employee visit so delete is safe.
        create_r = self.admin_client.post(
            "/api/v1/admin/visits/",
            {
                "farmer_id": self.farmer.id,
                "crop_id": self.crop.id,
                "employee_id": self.employee.id,
                "latitude": 12.98,
                "longitude": 77.60,
                "notes": "admin created visit",
            },
            format="json",
        )
        self.assertIn(
            create_r.status_code,
            {status.HTTP_200_OK, status.HTTP_201_CREATED},
            msg=getattr(create_r, "data", create_r.content),
        )
        created_visit_id = (
            create_r.data.get("data", {}).get("id")
            or create_r.data.get("id")
            or (create_r.data.get("data") or {}).get("visit_id")
        )
        self.assertTrue(created_visit_id)

        delete_r = self.admin_client.delete(f"/api/v1/admin/visits/{created_visit_id}/")
        self.assertEqual(delete_r.status_code, status.HTTP_200_OK)

    def test_staff_admin_issue_and_recommendation_crud(self):
        list_r = self.admin_client.get("/api/v1/admin/issues/")
        self.assertEqual(list_r.status_code, status.HTTP_200_OK)

        detail_r = self.admin_client.get(f"/api/v1/admin/issues/{self.issue.id}/")
        self.assertEqual(detail_r.status_code, status.HTTP_200_OK)

        create_r = self.admin_client.post(
            "/api/v1/admin/issues/",
            {
                "visit_id": self.visit.id,
                "crop_id": self.crop.id,
                "severity": "high",
                "status": "open",
                "description": "Admin issue",
            },
            format="json",
        )
        self.assertEqual(
            create_r.status_code,
            status.HTTP_201_CREATED,
            msg=getattr(create_r, "data", create_r.content),
        )
        issue_id = create_r.data["id"]

        patch_r = self.admin_client.patch(
            f"/api/v1/admin/issues/{issue_id}/",
            {"status": "resolved"},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)

        rec_create = self.admin_client.post(
            "/api/v1/admin/recommendations/",
            {
                "issue": issue_id,
                "given_by": self.staff_admin.id,
                "fertilizer": "Urea",
                "notes": "admin rec",
            },
            format="json",
        )
        self.assertEqual(rec_create.status_code, status.HTTP_201_CREATED)
        rec_id = rec_create.data["id"]

        rec_patch = self.admin_client.patch(
            f"/api/v1/admin/recommendations/{rec_id}/",
            {"notes": "admin rec updated"},
            format="json",
        )
        self.assertEqual(rec_patch.status_code, status.HTTP_200_OK)

        rec_del = self.admin_client.delete(f"/api/v1/admin/recommendations/{rec_id}/")
        self.assertIn(
            rec_del.status_code, {status.HTTP_200_OK, status.HTTP_204_NO_CONTENT}
        )

        issue_del = self.admin_client.delete(f"/api/v1/admin/issues/{issue_id}/")
        self.assertIn(
            issue_del.status_code, {status.HTTP_200_OK, status.HTTP_204_NO_CONTENT}
        )

    def test_staff_admin_masters_crud(self):
        # Crops
        crop_list = self.admin_client.get("/api/v1/admin/crop-catalog/")
        self.assertEqual(crop_list.status_code, status.HTTP_200_OK)
        crop_create = self.admin_client.post(
            "/api/v1/admin/crop-catalog/",
            {"name_en": "Cotton", "name_ta": "Cotton", "is_active": True},
            format="json",
        )
        self.assertEqual(crop_create.status_code, status.HTTP_201_CREATED)
        crop_id = crop_create.data["id"]
        crop_patch = self.admin_client.patch(
            f"/api/v1/admin/crop-catalog/{crop_id}/",
            {"name_en": "Cotton Updated"},
            format="json",
        )
        self.assertEqual(crop_patch.status_code, status.HTTP_200_OK)

        # Districts / villages via masters API
        dist_create = self.admin_client.post(
            "/api/v1/masters/districts/",
            {"name": "Staff District"},
            format="json",
        )
        self.assertEqual(dist_create.status_code, status.HTTP_201_CREATED)
        dist_id = dist_create.data.get("id") or dist_create.data.get("data", {}).get("id")
        if dist_id is None:
            # Some masters endpoints wrap payloads.
            dist_id = District.objects.get(name="Staff District").id

        village_create = self.admin_client.post(
            "/api/v1/masters/villages/",
            {"name": "Staff Village", "district": dist_id},
            format="json",
        )
        self.assertEqual(village_create.status_code, status.HTTP_201_CREATED)

        cat_create = self.admin_client.post(
            "/api/v1/admin/problem-categories/",
            {"name": "CRUD Disease", "code": "crud_disease_test", "is_active": True},
            format="json",
        )
        self.assertEqual(cat_create.status_code, status.HTTP_201_CREATED)
        cat_id = cat_create.data["id"]
        cat_patch = self.admin_client.patch(
            f"/api/v1/admin/problem-categories/{cat_id}/",
            {"name": "Disease Updated"},
            format="json",
        )
        self.assertEqual(cat_patch.status_code, status.HTTP_200_OK)

    def test_staff_admin_employee_crud_but_not_owner(self):
        list_r = self.admin_client.get("/api/v1/employees/admin/employees/")
        self.assertEqual(list_r.status_code, status.HTTP_200_OK)

        create_r = self.admin_client.post(
            "/api/v1/employees/admin/employees/",
            {
                "first_name": "NewField",
                "phone": "9000000099",
                "role": "FieldAgent",
            },
            format="json",
        )
        self.assertEqual(
            create_r.status_code,
            status.HTTP_201_CREATED,
            msg=getattr(create_r, "data", create_r.content),
        )
        create_data = create_r.data.get("data") or create_r.data
        self.assertEqual(create_data["username"], "KAC-NEWFIELD01")
        self.assertIn("temporary_password", create_data)
        created_profile = EmployeeProfile.objects.get(
            user__username=create_data["username"]
        )

        detail_r = self.admin_client.get(
            f"/api/v1/employees/admin/employees/{created_profile.id}/"
        )
        self.assertEqual(detail_r.status_code, status.HTTP_200_OK)

        patch_r = self.admin_client.patch(
            f"/api/v1/employees/admin/employees/{created_profile.id}/",
            {"first_name": "Updated"},
            format="json",
        )
        self.assertEqual(patch_r.status_code, status.HTTP_200_OK)

        toggle_r = self.admin_client.patch(
            f"/api/v1/employees/admin/employees/{created_profile.id}/toggle-status/"
        )
        self.assertEqual(toggle_r.status_code, status.HTTP_200_OK)

        delete_r = self.admin_client.delete(
            f"/api/v1/employees/admin/employees/{created_profile.id}/"
        )
        self.assertEqual(delete_r.status_code, status.HTTP_200_OK)

        owner_profile = self.owner.employee_profile
        blocked_patch = self.admin_client.patch(
            f"/api/v1/employees/admin/employees/{owner_profile.id}/",
            {"first_name": "Hacked"},
            format="json",
        )
        self.assertEqual(blocked_patch.status_code, status.HTTP_403_FORBIDDEN)

        blocked_delete = self.admin_client.delete(
            f"/api/v1/employees/admin/employees/{owner_profile.id}/"
        )
        self.assertEqual(blocked_delete.status_code, status.HTTP_403_FORBIDDEN)

        blocked_toggle = self.admin_client.patch(
            f"/api/v1/employees/admin/employees/{owner_profile.id}/toggle-status/"
        )
        self.assertEqual(blocked_toggle.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot create another admin user
        create_admin = self.admin_client.post(
            "/api/v1/employees/create-admin/",
            {
                "username": "another.admin",
                "password": STRONG_PASSWORD,
                "phone": "9000000077",
            },
            format="json",
        )
        self.assertEqual(create_admin.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_admin_cannot_mutate_system_config(self):
        get_r = self.admin_client.get("/api/v1/system/config/")
        self.assertEqual(get_r.status_code, status.HTTP_200_OK)
        put_r = self.admin_client.put(
            "/api/v1/system/config/",
            {"heartbeat_timeout_minutes": 99},
            format="json",
        )
        self.assertEqual(put_r.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_create_admin(self):
        r = self.owner_client.post(
            "/api/v1/employees/create-admin/",
            {
                "username": "staff.from.owner",
                "password": STRONG_PASSWORD,
                "phone": "9000000066",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        created = User.objects.get(username="staff.from.owner")
        self.assertTrue(created.is_staff)
        self.assertFalse(created.is_superuser)
