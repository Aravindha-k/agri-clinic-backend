from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import EmployeeProfile
from masters.models import Crop, District, Farmer, Village
from mobile_api.test_helpers import login_mobile_client
from visits.models import Visit
from visits.submitted import submitted_visits_qs


class MobileVisitDateFilterTest(APITestCase):
    def setUp(self):
        self.employee = User.objects.create_user(username="filter_emp", password="x")
        EmployeeProfile.objects.create(
            user=self.employee,
            employee_id="EMP-FILTER",
            phone="9000000999",
            is_active_employee=True,
        )
        self.client = login_mobile_client(employee_id="EMP-FILTER")

        district = District.objects.create(name="Filter D")
        village = Village.objects.create(name="Filter V", district=district)
        self.farmer = Farmer.objects.create(
            name="Filter Farmer",
            phone="9888777666",
            district=district,
            village=village,
        )
        self.crop = Crop.objects.create(name_en="Rice", name_ta="Rice", is_active=True)

        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=15)

        base = {
            "employee": self.employee,
            "farmer": self.farmer,
            "crop": self.crop,
            "latitude": 12.97,
            "longitude": 77.59,
            "status": "completed",
        }
        self.today_visit = Visit.objects.create(**base, visit_date=today)
        self.week_visit = Visit.objects.create(**base, visit_date=week_start)
        self.old_visit = Visit.objects.create(**base, visit_date=last_month)

        submitted_visits_qs().filter(
            pk__in=[self.today_visit.pk, self.week_visit.pk, self.old_visit.pk]
        ).exists()

    def _result_ids(self, response):
        self.assertEqual(response.status_code, 200)
        return {row["id"] for row in response.data["data"]["results"]}

    def test_date_filter_today(self):
        ids = self._result_ids(
            self.client.get("/api/v1/mobile/visits/", {"date_filter": "today"})
        )
        self.assertEqual(ids, {self.today_visit.id})

    def test_date_filter_week(self):
        ids = self._result_ids(
            self.client.get("/api/v1/mobile/visits/", {"date_filter": "week"})
        )
        self.assertEqual(ids, {self.today_visit.id, self.week_visit.id})

    def test_date_filter_month(self):
        ids = self._result_ids(
            self.client.get("/api/v1/mobile/visits/", {"date_filter": "month"})
        )
        self.assertEqual(ids, {self.today_visit.id, self.week_visit.id})

    def test_no_date_filter_returns_all(self):
        ids = self._result_ids(self.client.get("/api/v1/mobile/visits/"))
        self.assertEqual(
            ids,
            {self.today_visit.id, self.week_visit.id, self.old_visit.id},
        )
