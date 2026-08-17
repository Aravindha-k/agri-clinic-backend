"""Tests for admin-only employee location assignment reference master."""

from __future__ import annotations

import importlib
import pkgutil

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.employee_access import set_field_employee_active
from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from farmers.helpers import farmers_directory_queryset
from masters.models import District, Taluk, Village

STRONG = "SecurePass1!"
LIST_URL = "/api/v1/admin/employee-location-assignments/"


def make_admin(username="loc_admin", password=STRONG):
    user = User.objects.create_user(
        username=username, password=password, is_staff=True, is_active=True
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id=f"ADM-{user.id:04d}",
        phone="9000000001",
        role="Supervisor",
    )
    return user


def make_field_employee(
    username="KAC-KAVYA01",
    employee_id="KAC-0001",
    first_name="Kavya",
):
    user = User.objects.create_user(
        username=username,
        password=STRONG,
        is_staff=False,
        is_active=True,
        first_name=first_name,
    )
    profile = EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone="9000000002",
        role="FieldAgent",
    )
    return user, profile


class EmployeeLocationAssignmentFixtures(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.owner = User.objects.create_user(
            username="owner",
            password=STRONG,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        EmployeeProfile.objects.create(
            user=self.owner,
            employee_id="OWN-0001",
            phone="9000000000",
            role="Supervisor",
        )
        self.field_user, self.field_profile = make_field_employee()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.field_client = APIClient()
        self.field_client.force_authenticate(user=self.field_user)
        self.anon_client = APIClient()

        self.d1 = District.objects.create(name="Villupuram")
        self.d2 = District.objects.create(name="Cuddalore")
        self.t_gingee = Taluk.objects.create(name="Gingee", district=self.d1)
        self.t_tindi = Taluk.objects.create(name="Tindivanam", district=self.d1)
        self.t_panruti = Taluk.objects.create(name="Panruti", district=self.d2)
        self.v_a = Village.objects.create(
            name="Village A", district=self.d1, taluk=self.t_gingee
        )
        self.v_b = Village.objects.create(
            name="Village B", district=self.d1, taluk=self.t_gingee
        )
        self.v_c = Village.objects.create(
            name="Village C", district=self.d1, taluk=self.t_tindi
        )
        self.v_d = Village.objects.create(
            name="Village D", district=self.d2, taluk=self.t_panruti
        )
        self.v_legacy = Village.objects.create(
            name="Legacy Null Taluk", district=self.d1, taluk=None
        )
        self.v_inactive = Village.objects.create(
            name="Inactive Village",
            district=self.d1,
            taluk=self.t_gingee,
            is_active=False,
        )

    def detail_url(self, profile_id=None):
        pid = profile_id or self.field_profile.id
        return f"/api/v1/admin/employees/{pid}/location-assignments/"


class EmployeeLocationAssignmentPermissionTests(EmployeeLocationAssignmentFixtures):
    def test_unauthenticated_list_401(self):
        resp = self.anon_client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_detail_401(self):
        resp = self.anon_client.get(self.detail_url())
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_field_employee_list_403(self):
        resp = self.field_client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_field_employee_detail_403(self):
        resp = self.field_client.get(self.detail_url())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_field_employee_write_403(self):
        resp = self.field_client.put(
            self.detail_url(),
            {"assignments": [{"district_id": self.d1.id, "village_ids": []}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_allowed(self):
        resp = self.admin_client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["success"])

    def test_owner_allowed(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)
        resp = client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class EmployeeLocationAssignmentCrudTests(EmployeeLocationAssignmentFixtures):
    def test_create_multiple_districts_taluks_villages(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id, self.v_b.id],
                },
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_tindi.id,
                    "village_ids": [self.v_c.id],
                },
                {
                    "district_id": self.d2.id,
                    "taluk_id": self.t_panruti.id,
                    "village_ids": [self.v_d.id],
                },
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertEqual(data["location_assignment_summary"]["district_count"], 2)
        self.assertEqual(data["location_assignment_summary"]["taluk_count"], 3)
        self.assertEqual(data["location_assignment_summary"]["village_count"], 4)
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                employee=self.field_profile
            ).count(),
            4,
        )

    def test_district_only_assignment(self):
        payload = {"assignments": [{"district_id": self.d1.id, "village_ids": []}]}
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = EmployeeLocationAssignment.objects.get(employee=self.field_profile)
        self.assertEqual(row.district_id, self.d1.id)
        self.assertIsNone(row.taluk_id)
        self.assertIsNone(row.village_id)

    def test_taluk_level_assignment(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = EmployeeLocationAssignment.objects.get(employee=self.field_profile)
        self.assertEqual(row.district_id, self.d1.id)
        self.assertEqual(row.taluk_id, self.t_gingee.id)
        self.assertIsNone(row.village_id)

    def test_removing_district_drops_child_taluk_and_village(self):
        first = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id, self.v_b.id],
                },
                {
                    "district_id": self.d2.id,
                    "taluk_id": self.t_panruti.id,
                    "village_ids": [self.v_d.id],
                },
            ]
        }
        self.admin_client.put(self.detail_url(), first, format="json")
        resp = self.admin_client.put(
            self.detail_url(),
            {
                "assignments": [
                    {
                        "district_id": self.d2.id,
                        "taluk_id": self.t_panruti.id,
                        "village_ids": [self.v_d.id],
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = EmployeeLocationAssignment.objects.filter(employee=self.field_profile)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().district_id, self.d2.id)
        self.assertFalse(
            EmployeeLocationAssignment.objects.filter(
                employee=self.field_profile, district=self.d1
            ).exists()
        )

    def test_removing_taluk_drops_child_villages(self):
        first = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id, self.v_b.id],
                },
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_tindi.id,
                    "village_ids": [self.v_c.id],
                },
            ]
        }
        self.admin_client.put(self.detail_url(), first, format="json")
        resp = self.admin_client.patch(
            self.detail_url(),
            {
                "assignments": [
                    {
                        "district_id": self.d1.id,
                        "taluk_id": self.t_tindi.id,
                        "village_ids": [self.v_c.id],
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = list(
            EmployeeLocationAssignment.objects.filter(employee=self.field_profile)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].taluk_id, self.t_tindi.id)
        self.assertEqual(rows[0].village_id, self.v_c.id)

    def test_exact_replacement_update(self):
        first = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id],
                }
            ]
        }
        self.admin_client.put(self.detail_url(), first, format="json")
        second = {
            "assignments": [
                {
                    "district_id": self.d2.id,
                    "taluk_id": self.t_panruti.id,
                    "village_ids": [self.v_d.id],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), second, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = EmployeeLocationAssignment.objects.filter(employee=self.field_profile)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().district_id, self.d2.id)

    def test_duplicate_groups_deduped(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id],
                },
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id],
                },
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                employee=self.field_profile
            ).count(),
            1,
        )

    def test_wrong_taluk_for_district_rejected(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d2.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_wrong_village_for_taluk_rejected(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_tindi.id,
                    "village_ids": [self.v_a.id],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_legacy_village_without_taluk_rejected(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_legacy.id],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_inactive_village_rejected(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_inactive.id],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)


class EmployeeLocationAssignmentListTests(EmployeeLocationAssignmentFixtures):
    def test_list_returns_summary_counts_not_all_villages(self):
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d1,
            taluk=self.t_gingee,
            village=self.v_a,
        )
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d1,
            taluk=self.t_gingee,
            village=self.v_b,
        )
        resp = self.admin_client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()["data"]
        row = next(
            r
            for r in body["results"]
            if r["employee"]["employee_id"] == self.field_profile.employee_id
        )
        summary = row["location_assignment_summary"]
        self.assertEqual(summary["district_count"], 1)
        self.assertEqual(summary["taluk_count"], 1)
        self.assertEqual(summary["village_count"], 2)
        preview = row["location_assignment_preview"]
        self.assertEqual(preview["districts"], [{"id": self.d1.id, "name": "Villupuram"}])
        self.assertEqual(preview["taluks"], [{"id": self.t_gingee.id, "name": "Gingee"}])
        self.assertEqual(
            {v["name"] for v in preview["villages"]},
            {"Village A", "Village B"},
        )
        self.assertNotIn("assignments", row)

    def test_list_preview_capped_and_empty_when_unassigned(self):
        for index in range(4):
            taluk = Taluk.objects.create(
                name=f"Taluk {index}",
                district=self.d1,
            )
            Village.objects.create(
                name=f"Village {index}",
                district=self.d1,
                taluk=taluk,
            )
            EmployeeLocationAssignment.objects.create(
                employee=self.field_profile,
                district=self.d1,
                taluk=taluk,
                village=Village.objects.get(name=f"Village {index}"),
            )

        resp = self.admin_client.get(LIST_URL)
        row = next(
            r
            for r in resp.json()["data"]["results"]
            if r["employee"]["employee_id"] == self.field_profile.employee_id
        )
        self.assertEqual(row["location_assignment_summary"]["taluk_count"], 4)
        self.assertEqual(len(row["location_assignment_preview"]["taluks"]), 3)
        self.assertEqual(len(row["location_assignment_preview"]["villages"]), 3)

        unassigned = make_field_employee(username="empty01", employee_id="KAC-EMPTY")
        resp_empty = self.admin_client.get(LIST_URL)
        empty_row = next(
            r
            for r in resp_empty.json()["data"]["results"]
            if r["employee"]["employee_id"] == unassigned[1].employee_id
        )
        self.assertEqual(
            empty_row["location_assignment_preview"],
            {"districts": [], "taluks": [], "villages": []},
        )

    def test_filter_by_district(self):
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d2,
            taluk=self.t_panruti,
            village=self.v_d,
        )
        resp = self.admin_client.get(f"{LIST_URL}?district={self.d2.id}")
        ids = {r["employee"]["id"] for r in resp.json()["data"]["results"]}
        self.assertIn(self.field_profile.id, ids)


class EmployeeLocationAssignmentEmployeeLifecycleTests(
    EmployeeLocationAssignmentFixtures
):
    def test_deactivate_preserves_assignments(self):
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d1,
            taluk=self.t_gingee,
            village=self.v_a,
        )
        set_field_employee_active(self.field_profile, active=False, reason="test")
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                employee=self.field_profile
            ).count(),
            1,
        )
        resp = self.admin_client.get(self.detail_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp.json()["data"]["location_assignment_summary"]["village_count"], 1
        )

    def test_reactivate_preserves_assignments(self):
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d1,
            taluk=self.t_gingee,
            village=self.v_a,
        )
        set_field_employee_active(self.field_profile, active=False, reason="test")
        set_field_employee_active(self.field_profile, active=True, reason="test")
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                employee=self.field_profile
            ).count(),
            1,
        )


class EmployeeLocationAssignmentReferenceOnlyTests(EmployeeLocationAssignmentFixtures):
    OPERATIONAL_MODULES = (
        "farmers.helpers",
        "farmers.access",
        "visits.access",
        "tracking.services",
        "tracking.duty_service",
        "tracking.gps_service",
        "mobile_api.auth",
        "accounts.employee_access",
        "reports.summary",
    )

    def test_operational_modules_do_not_import_assignment_model(self):
        for module_name in self.OPERATIONAL_MODULES:
            module = importlib.import_module(module_name)
            source_path = getattr(module, "__file__", "")
            self.assertTrue(source_path)
            with open(source_path, encoding="utf-8") as handle:
                source = handle.read()
            self.assertNotIn(
                "EmployeeLocationAssignment",
                source,
                msg=f"{module_name} must not reference EmployeeLocationAssignment",
            )

    def test_farmer_directory_unaffected_after_assignment(self):
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d1,
            taluk=self.t_gingee,
            village=self.v_a,
        )
        before = farmers_directory_queryset().count()
        after = farmers_directory_queryset().count()
        self.assertEqual(before, after)

    def test_assignment_package_not_imported_by_operational_apps(self):
        forbidden = (
            "accounts.location_assignments",
            "accounts.location_assignment_views",
        )
        import farmers
        import mobile_api
        import tracking
        import visits

        packages = (farmers, visits, tracking, mobile_api)
        for pkg in packages:
            for module_info in pkgutil.walk_packages(
                pkg.__path__, prefix=pkg.__name__ + "."
            ):
                if module_info.name.endswith("tests") or ".tests" in module_info.name:
                    continue
                try:
                    module = importlib.import_module(module_info.name)
                except Exception:
                    continue
                source_path = getattr(module, "__file__", "") or ""
                if not source_path.endswith(".py"):
                    continue
                with open(source_path, encoding="utf-8") as handle:
                    source = handle.read()
                for forbidden_module in forbidden:
                    self.assertNotIn(
                        forbidden_module,
                        source,
                        msg=f"{module_info.name} imports assignment reference module",
                    )
