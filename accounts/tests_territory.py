"""Phase 1 employee territory isolation tests."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from accounts.territory import get_employee_assigned_village_ids
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Taluk, Village
from mobile_api.test_helpers import assign_operational_territory, login_mobile_client
from visits.models import Visit

STRONG = "SecurePass1!"


def _make_admin():
    user = User.objects.create_user(
        username="terr_admin",
        password=STRONG,
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    EmployeeProfile.objects.create(
        user=user,
        employee_id="ADM-TERR",
        phone="9000000100",
        role="Supervisor",
    )
    return user


def _make_employee(username, employee_id, phone):
    user = User.objects.create_user(
        username=username,
        password=STRONG,
        is_staff=False,
        first_name=username,
    )
    profile = EmployeeProfile.objects.create(
        user=user,
        employee_id=employee_id,
        phone=phone,
        role="FieldAgent",
        is_active_employee=True,
        can_login=True,
    )
    return user, profile


class EmployeeTerritoryIsolationTests(TestCase):
    def setUp(self):
        self.admin = _make_admin()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

        self.emp_a, self.profile_a = _make_employee("emp_a", "EMP-A", "9000000001")
        self.emp_b, self.profile_b = _make_employee("emp_b", "EMP-B", "9000000002")
        self.emp_empty, self.profile_empty = _make_employee(
            "emp_empty", "EMP-EMPTY", "9000000003"
        )

        self.district_a = District.objects.create(name="District A")
        self.district_b = District.objects.create(name="District B")
        self.taluk_a = Taluk.objects.create(name="Taluk A", district=self.district_a)
        self.taluk_b = Taluk.objects.create(name="Taluk B", district=self.district_b)
        self.village_a1 = Village.objects.create(
            name="Village A1", district=self.district_a, taluk=self.taluk_a
        )
        self.village_a2 = Village.objects.create(
            name="Village A2", district=self.district_a, taluk=self.taluk_a
        )
        self.village_b1 = Village.objects.create(
            name="Village B1", district=self.district_b, taluk=self.taluk_b
        )
        self.village_b2 = Village.objects.create(
            name="Village B2", district=self.district_b, taluk=self.taluk_b
        )

        assign_operational_territory(self.emp_a, self.village_a1)
        assign_operational_territory(self.emp_a, self.village_a2)
        assign_operational_territory(self.emp_b, self.village_b1)

        self.farmer_a1 = Farmer.objects.create(
            name="Kedara Farmer",
            phone="9111000001",
            district=self.district_a,
            taluk=self.taluk_a,
            village=self.village_a1,
            assigned_employee=self.emp_a,
        )
        self.farmer_a2 = Farmer.objects.create(
            name="Ananthapuram Farmer",
            phone="9111000002",
            district=self.district_a,
            taluk=self.taluk_a,
            village=self.village_a2,
            assigned_employee=self.emp_a,
        )
        self.farmer_b1 = Farmer.objects.create(
            name="Other District Farmer",
            phone="9111000003",
            district=self.district_b,
            taluk=self.taluk_b,
            village=self.village_b1,
            assigned_employee=self.emp_b,
        )
        self.farmer_b2 = Farmer.objects.create(
            name="Same Taluk Unassigned Farmer",
            phone="9111000005",
            district=self.district_b,
            taluk=self.taluk_b,
            village=self.village_b2,
            assigned_employee=self.emp_b,
        )
        self.archived_a1 = Farmer.objects.create(
            name="Archived A1",
            phone="9111000004",
            district=self.district_a,
            taluk=self.taluk_a,
            village=self.village_a1,
            is_active=False,
        )

        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)
        self.category, _ = ProblemCategory.objects.get_or_create(
            code="pest_terr",
            defaults={"name": "Pest Terr", "requires_problem_master": True},
        )
        self.problem = ProblemMaster.objects.create(
            category=self.category, name="Stem borer", crop=self.crop
        )

        self.client_a = login_mobile_client(employee_id="EMP-A", password=STRONG)
        self.client_b = login_mobile_client(employee_id="EMP-B", password=STRONG)
        self.client_empty = login_mobile_client(employee_id="EMP-EMPTY", password=STRONG)

    def _visit_payload(self, farmer, village):
        return {
            "farmer_id": farmer.id,
            "farmer_name": farmer.name,
            "phone_number": farmer.phone,
            "village_id": village.id,
            "crop_id": self.crop.id,
            "acreage": 1.25,
            "problem_category_id": self.category.id,
            "problem_master_id": self.problem.id,
            "problem_description": "Leaf damage",
            "latitude": 12.97,
            "longitude": 77.59,
        }

    def _farmer_ids(self, response):
        data = response.data
        rows = data.get("results") if isinstance(data, dict) else data
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            rows = data["data"].get("results", data["data"])
        return {row["id"] for row in rows}

    def test_territory_helpers_are_village_only(self):
        self.assertEqual(
            get_employee_assigned_village_ids(self.emp_a),
            frozenset({self.village_a1.id, self.village_a2.id}),
        )
        self.assertEqual(
            get_employee_assigned_village_ids(self.emp_b),
            frozenset({self.village_b1.id}),
        )
        self.assertEqual(get_employee_assigned_village_ids(self.emp_empty), frozenset())

    def test_legacy_district_only_row_does_not_grant_territory(self):
        EmployeeLocationAssignment.objects.create(
            employee=self.profile_empty,
            district=self.district_a,
            taluk=None,
            village=None,
            is_active=True,
            is_operational=False,
        )
        self.assertEqual(get_employee_assigned_village_ids(self.emp_empty), frozenset())

    def test_mobile_territory_employee_a(self):
        resp = self.client_a.get("/api/v1/mobile/territory/")
        self.assertEqual(resp.status_code, 200)
        villages = resp.json()["data"]["villages"]
        village_ids = {v["id"] for v in villages}
        self.assertEqual(village_ids, {self.village_a1.id, self.village_a2.id})
        self.assertNotIn(self.village_b1.id, village_ids)
        self.assertTrue(all("name_ta" in row for row in villages))
        self.assertTrue(all("is_active" in row for row in villages))

    def test_mobile_territory_employee_b(self):
        resp = self.client_b.get("/api/v1/mobile/territory/")
        self.assertEqual(resp.status_code, 200)
        village_ids = {v["id"] for v in resp.json()["data"]["villages"]}
        self.assertEqual(village_ids, {self.village_b1.id})
        self.assertNotIn(self.village_b2.id, village_ids)
        self.assertNotIn(self.village_a1.id, village_ids)

    def test_empty_assignment_returns_empty_not_all(self):
        resp = self.client_empty.get("/api/v1/mobile/territory/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["villages"], [])

        farmers = self.client_empty.get("/api/v1/mobile/farmers/", {"page_size": 100})
        self.assertEqual(farmers.status_code, 200)
        self.assertEqual(farmers.data["count"], 0)
        self.assertEqual(farmers.data["results"], [])

        options = self.client_empty.get("/api/v1/mobile/visit-form-options/")
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.json()["data"]["villages"], [])

        create = self.client_empty.post(
            "/api/v1/farmers/",
            {
                "name": "No Territory Farmer",
                "phone": "9111777000",
                "village": self.village_a1.id,
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_400_BAD_REQUEST)
        visit = self.client_empty.post(
            "/api/v1/mobile/visits/",
            self._visit_payload(self.farmer_a1, self.village_a1),
            format="json",
        )
        self.assertEqual(visit.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_taluk_does_not_grant_unassigned_village(self):
        farmers = self.client_b.get("/api/v1/mobile/farmers/", {"page_size": 100})
        ids = self._farmer_ids(farmers)
        self.assertEqual(ids, {self.farmer_b1.id})
        self.assertNotIn(self.farmer_b2.id, ids)

        detail = self.client_b.get(f"/api/v1/farmers/{self.farmer_b2.id}/")
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        create = self.client_b.post(
            "/api/v1/farmers/",
            {
                "name": "B2 Hijack",
                "phone": "9111666000",
                "village": self.village_b2.id,
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_400_BAD_REQUEST)
        visit = self.client_b.post(
            "/api/v1/mobile/visits/",
            self._visit_payload(self.farmer_b2, self.village_b2),
            format="json",
        )
        self.assertEqual(visit.status_code, status.HTTP_400_BAD_REQUEST)

        masters = self.client_b.get("/api/v1/masters/villages/?page_size=500")
        self.assertEqual(masters.status_code, 200)
        body = masters.json()
        data = body.get("data", body)
        rows = data.get("results", data)
        village_ids = {row["id"] for row in rows}
        self.assertEqual(village_ids, {self.village_b1.id})
        self.assertNotIn(self.village_b2.id, village_ids)

    def test_employee_a_farmer_directory_territory_and_active(self):
        resp = self.client_a.get("/api/v1/mobile/farmers/", {"page_size": 100})
        ids = self._farmer_ids(resp)
        self.assertEqual(ids, {self.farmer_a1.id, self.farmer_a2.id})
        self.assertNotIn(self.farmer_b1.id, ids)
        self.assertNotIn(self.farmer_b2.id, ids)
        self.assertNotIn(self.archived_a1.id, ids)

        shared = self.client_a.get("/api/v1/farmers/", {"page_size": 100})
        self.assertEqual(self._farmer_ids(shared), ids)

    def test_employee_a_cannot_read_b1_farmer_detail(self):
        resp = self.client_a.get(f"/api/v1/mobile/farmers/{self.farmer_b1.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        resp2 = self.client_a.get(f"/api/v1/farmers/{self.farmer_b1.id}/")
        self.assertEqual(resp2.status_code, status.HTTP_404_NOT_FOUND)

    def test_archived_farmer_excluded_from_directory_and_detail(self):
        resp = self.client_a.get(f"/api/v1/farmers/{self.archived_a1.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_employee_a_cannot_create_farmer_in_b1(self):
        resp = self.client_a.post(
            "/api/v1/farmers/",
            {
                "name": "Hijack Farmer",
                "phone": "9111999999",
                "village": self.village_b1.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Farmer.objects.filter(phone="9111999999").exists())

    def test_employee_a_cannot_update_farmer_into_b1(self):
        resp = self.client_a.patch(
            f"/api/v1/farmers/{self.farmer_a1.id}/",
            {"village": self.village_b1.id},
            format="json",
        )
        self.assertIn(resp.status_code, {status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN})
        self.farmer_a1.refresh_from_db()
        self.assertEqual(self.farmer_a1.village_id, self.village_a1.id)

    def test_employee_a_create_farmer_village_only(self):
        resp = self.client_a.post(
            "/api/v1/farmers/",
            {
                "name": "New A1 Farmer",
                "phone": "9111888001",
                "village": self.village_a1.id,
                "district": self.district_b.id,
                "taluk": self.taluk_b.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        farmer = Farmer.objects.get(phone="9111888001")
        self.assertEqual(farmer.village_id, self.village_a1.id)
        self.assertIsNone(farmer.taluk_id)
        self.assertIsNone(farmer.district_id)

    def test_employee_a_cannot_create_visit_in_b1(self):
        resp = self.client_a.post(
            "/api/v1/mobile/visits/",
            self._visit_payload(self.farmer_b1, self.village_b1),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Visit.objects.filter(employee=self.emp_a).exists())

    def test_archived_farmer_not_selected_by_phone_for_new_visit(self):
        payload = self._visit_payload(self.archived_a1, self.village_a1)
        payload.pop("farmer_id")
        payload["phone_number"] = self.archived_a1.phone
        payload["farmer_name"] = self.archived_a1.name
        resp = self.client_a.post("/api/v1/mobile/visits/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Visit.objects.filter(farmer=self.archived_a1).exists())

    def test_historical_owned_visit_remains_readable_when_farmer_archived(self):
        visit = Visit.objects.create(
            employee=self.emp_a,
            farmer=self.archived_a1,
            farmer_name=self.archived_a1.name,
            farmer_phone=self.archived_a1.phone,
            village=self.village_a1,
            crop=self.crop,
            land_area=1.0,
            problem_category=self.category,
            problem_master=self.problem,
            problem_description="Historical issue",
            latitude=12.9,
            longitude=77.5,
        )
        resp = self.client_a.get(f"/api/v1/mobile/visits/{visit.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertEqual(body["id"], visit.id)
        farmer_block = body.get("farmer") or {}
        self.assertEqual(farmer_block.get("id"), self.archived_a1.id)

    def test_prefix_search_inside_territory_only(self):
        resp = self.client_a.get(
            "/api/v1/mobile/farmers/",
            {"search": "Ked", "page_size": 100},
        )
        ids = self._farmer_ids(resp)
        self.assertIn(self.farmer_a1.id, ids)
        self.assertNotIn(self.farmer_b1.id, ids)

        miss = self.client_a.get(
            "/api/v1/mobile/farmers/",
            {"search": "edar", "page_size": 100},
        )
        self.assertNotIn(self.farmer_a1.id, self._farmer_ids(miss))

        leak = self.client_a.get(
            "/api/v1/mobile/farmers/",
            {"search": "Other", "page_size": 100},
        )
        self.assertNotIn(self.farmer_b1.id, self._farmer_ids(leak))

    def test_pagination_after_territory_restriction(self):
        extra = []
        for i in range(3):
            extra.append(
                Farmer.objects.create(
                    name=f"Kedara Extra {i}",
                    phone=f"91117000{i:02d}",
                    district=self.district_a,
                    taluk=self.taluk_a,
                    village=self.village_a1,
                )
            )
        Farmer.objects.create(
            name="Kedara Outsider",
            phone="9111700099",
            district=self.district_b,
            taluk=self.taluk_b,
            village=self.village_b1,
        )
        resp = self.client_a.get(
            "/api/v1/mobile/farmers/",
            {"search": "Ked", "page_size": 2, "page": 1},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 4)
        self.assertEqual(len(resp.data["results"]), 2)
        ids = self._farmer_ids(resp)
        self.assertTrue(ids.issubset({self.farmer_a1.id, *[f.id for f in extra]}))

    def test_admin_master_access_unscoped(self):
        resp = self.admin_client.get("/api/v1/masters/villages/?page_size=500")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        data = body.get("data", body)
        rows = data.get("results", data)
        ids = {row["id"] for row in rows}
        self.assertTrue(
            {self.village_a1.id, self.village_a2.id, self.village_b1.id, self.village_b2.id}.issubset(ids)
        )
        farmers = self.admin_client.get("/api/v1/farmers/", {"page_size": 100})
        farmer_ids = self._farmer_ids(farmers)
        self.assertIn(self.farmer_b1.id, farmer_ids)
        self.assertIn(self.archived_a1.id, farmer_ids)

    def test_admin_rejects_district_only_assignment_write(self):
        url = f"/api/v1/admin/employees/{self.profile_empty.id}/location-assignments/"
        resp = self.admin_client.put(
            url,
            {"assignments": [{"district_id": self.district_a.id, "village_ids": []}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertFalse(
            EmployeeLocationAssignment.objects.filter(employee=self.profile_empty).exists()
        )

    def test_employee_b_cannot_read_or_write_a1(self):
        resp = self.client_b.get(f"/api/v1/farmers/{self.farmer_a1.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        create = self.client_b.post(
            "/api/v1/farmers/",
            {
                "name": "B Hijack",
                "phone": "9111999888",
                "village": self.village_a1.id,
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_400_BAD_REQUEST)
        visit = self.client_b.post(
            "/api/v1/mobile/visits/",
            self._visit_payload(self.farmer_a1, self.village_a1),
            format="json",
        )
        self.assertEqual(visit.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_legacy_fields_are_not_territory_source(self):
        self.profile_empty.district = self.district_a
        self.profile_empty.village = self.village_a1
        self.profile_empty.save()
        self.assertEqual(get_employee_assigned_village_ids(self.emp_empty), frozenset())
        resp = self.client_empty.get("/api/v1/mobile/territory/")
        self.assertEqual(resp.json()["data"]["villages"], [])

    def test_named_villages_abc_employee_isolation(self):
        village_a = Village.objects.create(name="Village A", name_ta="கிராமம் ஏ")
        village_b = Village.objects.create(name="Village B", name_ta="கிராமம் பி")
        village_c = Village.objects.create(name="Village C", name_ta="கிராமம் சி")
        EmployeeLocationAssignment.objects.filter(employee=self.profile_a).delete()
        EmployeeLocationAssignment.objects.filter(employee=self.profile_b).delete()
        assign_operational_territory(self.emp_a, village_a)
        assign_operational_territory(self.emp_a, village_b)
        assign_operational_territory(self.emp_b, village_c)

        farmer_a = Farmer.objects.create(
            name="Farmer A", phone="9111800001", village=village_a
        )
        farmer_b = Farmer.objects.create(
            name="Farmer B", phone="9111800002", village=village_b
        )
        Farmer.objects.create(name="Farmer C", phone="9111800003", village=village_c)

        client_a = login_mobile_client(employee_id="EMP-A", password=STRONG)
        client_b = login_mobile_client(employee_id="EMP-B", password=STRONG)

        a_villages = {row["name"] for row in client_a.get("/api/v1/mobile/territory/").json()["data"]["villages"]}
        self.assertEqual(a_villages, {"Village A", "Village B"})
        b_villages = {row["name"] for row in client_b.get("/api/v1/mobile/territory/").json()["data"]["villages"]}
        self.assertEqual(b_villages, {"Village C"})

        a_farmers = self._farmer_ids(client_a.get("/api/v1/mobile/farmers/", {"page_size": 100}))
        self.assertEqual(a_farmers, {farmer_a.id, farmer_b.id})

        blocked = client_a.post(
            "/api/v1/farmers/",
            {"name": "Into C", "phone": "9111800099", "village": village_c.id},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

        visit_ok = client_a.post(
            "/api/v1/mobile/visits/",
            self._visit_payload(farmer_a, village_a),
            format="json",
        )
        self.assertIn(visit_ok.status_code, {status.HTTP_200_OK, status.HTTP_201_CREATED}, visit_ok.data)
        visit_blocked = client_a.post(
            "/api/v1/mobile/visits/",
            self._visit_payload(farmer_a, village_c),
            format="json",
        )
        self.assertEqual(visit_blocked.status_code, status.HTTP_400_BAD_REQUEST)

    def test_village_without_taluk_is_operational(self):
        village = Village.objects.create(name="Standalone Kedar", name_ta="கேடார்")
        assign_operational_territory(self.emp_empty, village)
        self.assertEqual(
            get_employee_assigned_village_ids(self.emp_empty),
            frozenset({village.id}),
        )
        resp = self.client_empty.get("/api/v1/mobile/territory/")
        rows = resp.json()["data"]["villages"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Standalone Kedar")
        self.assertEqual(rows[0]["name_ta"], "கேடார்")
        self.assertTrue(rows[0]["is_active"])

    def test_tamil_village_prefix_search(self):
        self.village_a1.name_ta = "கேடார்"
        self.village_a1.save(update_fields=["name_ta"])
        resp = self.admin_client.get("/api/v1/masters/villages/", {"search": "கேட"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        data = body.get("data", body)
        rows = data.get("results", data)
        names = {row["name"] for row in rows}
        self.assertIn(self.village_a1.name, names)
        miss = self.admin_client.get("/api/v1/masters/villages/", {"search": "டார்"})
        miss_body = miss.json()
        miss_data = miss_body.get("data", miss_body)
        miss_rows = miss_data.get("results", miss_data)
        self.assertNotIn(self.village_a1.name, {row["name"] for row in miss_rows})

