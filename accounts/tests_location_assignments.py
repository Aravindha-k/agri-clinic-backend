"""Tests for admin-only employee location assignment reference master."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.employee_access import set_field_employee_active
from accounts.models import EmployeeLocationAssignment, EmployeeProfile
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
        self.assertEqual(data["location_assignment_summary"]["village_count"], 4)
        self.assertEqual(data["location_assignment_summary"]["district_count"], 0)
        self.assertEqual(data["location_assignment_summary"]["taluk_count"], 0)
        ids = {row["id"] for row in data["villages"]}
        self.assertEqual(ids, {self.v_a.id, self.v_b.id, self.v_c.id, self.v_d.id})
        self.assertTrue(all("name_ta" in row and "is_active" in row for row in data["villages"]))
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(
                employee=self.field_profile
            ).count(),
            4,
        )

    def test_district_only_assignment_rejected(self):
        payload = {"assignments": [{"district_id": self.d1.id, "village_ids": []}]}
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertFalse(
            EmployeeLocationAssignment.objects.filter(employee=self.field_profile).exists()
        )

    def test_taluk_level_assignment_rejected(self):
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
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertFalse(
            EmployeeLocationAssignment.objects.filter(employee=self.field_profile).exists()
        )

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
        self.assertEqual(rows.first().village_id, self.v_d.id)
        self.assertIsNone(rows.first().district_id)
        self.assertIsNone(rows.first().taluk_id)

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
        self.assertEqual(rows[0].village_id, self.v_c.id)
        self.assertIsNone(rows[0].taluk_id)
        self.assertIsNone(rows[0].district_id)

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
        self.assertEqual(rows.first().village_id, self.v_d.id)
        self.assertIsNone(rows.first().district_id)

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

    def test_wrong_village_for_taluk_still_assigns_village(self):
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
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = EmployeeLocationAssignment.objects.get(employee=self.field_profile)
        self.assertEqual(row.village_id, self.v_a.id)

    def test_legacy_village_without_taluk_can_be_assigned(self):
        payload = {"village_ids": [self.v_legacy.id]}
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        row = EmployeeLocationAssignment.objects.get(employee=self.field_profile)
        self.assertEqual(row.village_id, self.v_legacy.id)
        self.assertTrue(row.is_operational)

    def test_village_ids_payload_without_district(self):
        payload = {"village_ids": [self.v_a.id, self.v_c.id, self.v_a.id]}
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.json())
        data = resp.json()["data"]
        self.assertEqual(data["location_assignment_summary"]["village_count"], 2)
        ids = {row["id"] for row in data["villages"]}
        self.assertEqual(ids, {self.v_a.id, self.v_c.id})
        self.assertTrue(all(row["is_active"] for row in data["villages"]))
        for row in EmployeeLocationAssignment.objects.filter(employee=self.field_profile):
            self.assertIsNone(row.district_id)
            self.assertIsNone(row.taluk_id)

    def test_village_ids_full_replacement_drops_removed_villages(self):
        first = self.admin_client.put(
            self.detail_url(),
            {"village_ids": [self.v_a.id, self.v_b.id]},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.json())
        first_ids = {row["id"] for row in first.json()["data"]["villages"]}
        self.assertEqual(first_ids, {self.v_a.id, self.v_b.id})
        second = self.admin_client.put(
            self.detail_url(),
            {"village_ids": [self.v_b.id]},
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.json())
        data = second.json()["data"]
        self.assertEqual({row["id"] for row in data["villages"]}, {self.v_b.id})
        remaining = EmployeeLocationAssignment.objects.filter(employee=self.field_profile)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().village_id, self.v_b.id)
        self.assertIsNone(remaining.first().district_id)
        self.assertIsNone(remaining.first().taluk_id)

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
        self.assertEqual(summary["village_count"], 2)
        preview = row["location_assignment_preview"]
        self.assertEqual(preview["districts"], [])
        self.assertEqual(preview["taluks"], [])
        self.assertEqual(
            {v["name"] for v in preview["villages"]},
            {"Village A", "Village B"},
        )
        self.assertTrue(all("name_ta" in v and "is_active" in v for v in preview["villages"]))
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
        self.assertEqual(row["location_assignment_summary"]["village_count"], 4)
        self.assertEqual(len(row["location_assignment_preview"]["villages"]), 3)
        self.assertEqual(row["location_assignment_preview"]["taluks"], [])
        self.assertEqual(row["location_assignment_preview"]["districts"], [])

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


class EmployeeLocationAssignmentOperationalTests(EmployeeLocationAssignmentFixtures):
    def test_new_write_persists_village_level_operational_rows(self):
        payload = {
            "assignments": [
                {
                    "district_id": self.d1.id,
                    "taluk_id": self.t_gingee.id,
                    "village_ids": [self.v_a.id],
                }
            ]
        }
        resp = self.admin_client.put(self.detail_url(), payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = EmployeeLocationAssignment.objects.get(employee=self.field_profile)
        self.assertTrue(row.is_operational)
        self.assertEqual(row.village_id, self.v_a.id)
        self.assertIsNone(row.taluk_id)
        self.assertIsNone(row.district_id)

    def test_farmer_directory_unscoped_audit_queryset_unchanged(self):
        from farmers.helpers import farmers_directory_queryset

        before = farmers_directory_queryset().count()
        EmployeeLocationAssignment.objects.create(
            employee=self.field_profile,
            district=self.d1,
            taluk=self.t_gingee,
            village=self.v_a,
            is_operational=True,
        )
        after = farmers_directory_queryset().count()
        self.assertEqual(before, after)
