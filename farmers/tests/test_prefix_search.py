"""Regression tests for case-insensitive prefix API search."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from masters.models import (
    Crop,
    District,
    Farmer,
    ProblemCategory,
    ProblemMaster,
    Taluk,
    Village,
)


class PrefixSearchTestMixin:
    def _farmer_ids(self, response):
        data = response.data
        if isinstance(data, dict) and "results" in data:
            rows = data["results"]
        elif isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            rows = data["data"].get("results", data["data"])
        else:
            rows = data
        return {row["id"] for row in rows}

    def _paginated_rows(self, response):
        body = response.json()
        data = body.get("data", body)
        if isinstance(data, dict) and "results" in data:
            return data["results"], data.get("count")
        if isinstance(body, dict) and "results" in body:
            return body["results"], body.get("count")
        return data, None

    def _mobile_client(self, employee_user):
        client = APIClient()
        login = client.post(
            "/api/v1/mobile/auth/login/",
            {
                "employee_id": employee_user.employee_profile.employee_id,
                "password": "x",
                "device_name": "PrefixTestPhone",
                "platform": "android",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
            HTTP_X_DEVICE_SESSION=login.data["device_session_id"],
        )
        return client


class FarmerDirectoryPrefixSearchTests(PrefixSearchTestMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="prefix_admin",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.employee_user = User.objects.create_user(
            username="prefix_emp",
            password="x",
        )
        EmployeeProfile.objects.create(
            user=self.employee_user,
            employee_id="KAC-0003",
            phone="9000000003",
            role="FieldAgent",
            is_active_employee=True,
            can_login=True,
        )

        self.district = District.objects.create(name="Villupuram")
        self.taluk = Taluk.objects.create(name="Kallakurichi", district=self.district)
        self.village = Village.objects.create(
            name="Kedar",
            district=self.district,
            taluk=self.taluk,
        )
        self.target = Farmer.objects.create(
            name="Aravindh",
            phone="9626262922",
            farmer_code="FC-PREFIX-1",
            district=self.district,
            taluk=self.taluk,
            village=self.village,
            assigned_employee=self.employee_user,
        )
        self.decoy = Farmer.objects.create(
            name="Suresh",
            phone="9111111111",
            farmer_code="FC-DECOY",
            district=self.district,
            taluk=self.taluk,
            village=Village.objects.create(
                name="OtherVille",
                district=self.district,
                taluk=self.taluk,
            ),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _search(self, term: str, *, mobile: bool = False):
        path = "/api/v1/mobile/farmers/" if mobile else "/api/v1/farmers/"
        if mobile:
            client = self._mobile_client(self.employee_user)
        else:
            client = APIClient()
            client.force_authenticate(user=self.admin)
        return client.get(path, {"search": term, "page_size": 100})

    def test_prefix_name_matches(self):
        for term in ("Ara", "ARAV", "ara"):
            resp = self._search(term)
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertIn(self.target.id, self._farmer_ids(resp))

    def test_middle_name_substring_rejected(self):
        for term in ("rav", "vindh", "avind"):
            resp = self._search(term)
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertNotIn(self.target.id, self._farmer_ids(resp))

    def test_prefix_village_district_phone_match(self):
        resp = self._search("Ked")
        self.assertIn(self.target.id, self._farmer_ids(resp))
        resp = self._search("Vill")
        self.assertIn(self.target.id, self._farmer_ids(resp))
        resp = self._search("962")
        self.assertIn(self.target.id, self._farmer_ids(resp))

    def test_middle_phone_substring_rejected(self):
        resp = self._search("2626")
        self.assertNotIn(self.target.id, self._farmer_ids(resp))

    def test_middle_village_substring_rejected(self):
        resp = self._search("edar")
        self.assertNotIn(self.target.id, self._farmer_ids(resp))

    def test_middle_district_substring_rejected(self):
        resp = self._search("illup")
        self.assertNotIn(self.target.id, self._farmer_ids(resp))

    def test_empty_and_whitespace_search_returns_broader_list(self):
        full = self._search("")
        self.assertEqual(full.status_code, 200)
        self.assertGreaterEqual(full.data["count"], 2)
        blank = self._search("   ")
        self.assertEqual(blank.data["count"], full.data["count"])

    def test_mobile_farmer_search_uses_prefix(self):
        resp = self._search("Ara", mobile=True)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn(self.target.id, self._farmer_ids(resp))
        resp = self._search("rav", mobile=True)
        self.assertNotIn(self.target.id, self._farmer_ids(resp))

    def test_search_before_pagination(self):
        for i in range(5):
            Farmer.objects.create(
                name=f"Aravindh Batch {i}",
                phone=f"96000000{i:02d}",
                district=self.district,
                taluk=self.taluk,
                village=self.village,
            )
        resp = self.client.get(
            "/api/v1/farmers/",
            {"search": "Ara", "page_size": 2, "page": 1},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 6)
        self.assertEqual(len(resp.data["results"]), 2)


class ProblemItemPrefixSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="problem_prefix_admin",
            password="x",
            is_staff=True,
        )
        self.category = ProblemCategory.objects.create(name="Pest", code="pest")
        self.crop = Crop.objects.create(name_en="Tomato", name_ta="தக்காளி")
        self.item = ProblemMaster.objects.create(
            category=self.category,
            name="Whitefly",
            tamil_name="வெள்ளை ஈ",
            crop=self.crop,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_english_prefix_matches(self):
        resp = self.client.get("/api/v1/masters/problem-items/", {"search": "Whi"})
        self.assertEqual(resp.status_code, 200)
        names = [row["name"] for row in resp.data["data"]["results"]]
        self.assertIn("Whitefly", names)

    def test_english_middle_substring_rejected(self):
        resp = self.client.get("/api/v1/masters/problem-items/", {"search": "ite"})
        names = [row["name"] for row in resp.data["data"]["results"]]
        self.assertNotIn("Whitefly", names)

    def test_tamil_prefix_matches(self):
        resp = self.client.get(
            "/api/v1/masters/problem-items/",
            {"search": "வெள்"},
        )
        names = [row["name"] for row in resp.data["data"]["results"]]
        self.assertIn("Whitefly", names)


class LocationMasterPrefixSearchTests(PrefixSearchTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="loc_prefix", password="x")
        self.district = District.objects.create(name="Villupuram")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_district_prefix_match(self):
        resp = self.client.get("/api/v1/masters/districts/", {"search": "Vill"})
        self.assertEqual(resp.status_code, 200)
        rows, _ = self._paginated_rows(resp)
        names = [row["name"] for row in rows]
        self.assertIn("Villupuram", names)

    def test_district_middle_substring_rejected(self):
        resp = self.client.get("/api/v1/masters/districts/", {"search": "illup"})
        rows, _ = self._paginated_rows(resp)
        names = [row["name"] for row in rows]
        self.assertNotIn("Villupuram", names)


class EmployeePrefixSearchTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="emp_search_admin",
            password="x",
            is_staff=True,
        )
        self.employee_user = User.objects.create_user(
            username="KAC-KAVYA01",
            first_name="Kavya",
            password="x",
        )
        self.profile = EmployeeProfile.objects.create(
            user=self.employee_user,
            employee_id="KAC-0003",
            phone="9626000003",
            role="FieldAgent",
            is_active_employee=True,
            can_login=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_employee_code_prefix(self):
        resp = self.client.get(
            "/api/v1/employees/admin/employees/",
            {"search": "KAC"},
        )
        self.assertEqual(resp.status_code, 200)
        ids = {row["employee_id"] for row in resp.data["data"]["results"]}
        self.assertIn("KAC-0003", ids)

    def test_employee_code_suffix_rejected(self):
        resp = self.client.get(
            "/api/v1/employees/admin/employees/",
            {"search": "0003"},
        )
        ids = {row["employee_id"] for row in resp.data["data"]["results"]}
        self.assertNotIn("KAC-0003", ids)
