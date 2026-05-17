from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from visits.models import Visit
from visits.submitted import submitted_visits_qs
from tracking.worklog import WorkLog
from django.utils import timezone
from django.db.models import Sum

from drf_spectacular.utils import extend_schema
from utils.schema import SIMPLE_SUCCESS


@extend_schema(
    tags=["Reports"],
    summary="Daily visit and work report",
    description=(
        "Returns today's submitted visit counts and work hours. "
        "Non-staff users see only their own visits; staff see all visits for the date. "
        "Includes total work hours for the logged-in user."
    ),
    responses={200: SIMPLE_SUCCESS},
)
class DailyReportAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        visit_qs = submitted_visits_qs().filter(visit_date=today)
        if not request.user.is_staff:
            visit_qs = visit_qs.filter(employee=request.user)
        total_visits = visit_qs.count()
        total_work_hours = WorkLog.objects.filter(
            employee=request.user,
            start_time__date=today,
            is_active=False,
        ).aggregate(hours=Sum("total_duration"))["hours"]
        return Response(
            {
                "total_visits": total_visits,
                "total_work_hours": total_work_hours or 0,
            }
        )


@extend_schema(
    tags=["Reports"],
    summary="Monthly visit and work report",
    description=(
        "Returns this month's submitted visit counts. "
        "Includes total work hours for the logged-in user."
    ),
    responses={200: SIMPLE_SUCCESS},
)
class MonthlyReportAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        visit_qs = submitted_visits_qs().filter(
            visit_date__gte=month_start, visit_date__lte=today
        )
        if not request.user.is_staff:
            visit_qs = visit_qs.filter(employee=request.user)
        total_visits = visit_qs.count()
        total_work_hours = WorkLog.objects.filter(
            employee=request.user,
            start_time__date__gte=month_start,
            start_time__date__lte=today,
            is_active=False,
        ).aggregate(hours=Sum("total_duration"))["hours"]
        return Response(
            {
                "total_visits": total_visits,
                "total_work_hours": total_work_hours or 0,
            }
        )
