from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from visits.models import Visit
from tracking.worklog import WorkLog
from django.utils import timezone
from django.db.models import Sum

from drf_spectacular.utils import extend_schema
from utils.schema import SIMPLE_SUCCESS


@extend_schema(
    tags=["Reports"],
    summary="Daily visit and work report",
    description="Returns today's visit counts (total, pending, verified) and total work hours for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS},
)
class DailyReportAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        total_visits = Visit.objects.filter(visit_date=today).count()
        pending = Visit.objects.filter(visit_date=today, status="pending").count()
        verified = Visit.objects.filter(visit_date=today, status="verified").count()
        total_work_hours = WorkLog.objects.filter(
            employee=request.user,
            start_time__date=today,
            is_active=False,
        ).aggregate(hours=Sum("total_duration"))["hours"]
        return Response(
            {
                "total_visits": total_visits,
                "pending": pending,
                "verified": verified,
                "total_work_hours": total_work_hours or 0,
            }
        )


@extend_schema(
    tags=["Reports"],
    summary="Monthly visit and work report",
    description="Returns this month's visit counts and total work hours for the logged-in employee.",
    responses={200: SIMPLE_SUCCESS},
)
class MonthlyReportAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        total_visits = Visit.objects.filter(
            visit_date__gte=month_start, visit_date__lte=today
        ).count()
        pending = Visit.objects.filter(
            visit_date__gte=month_start, visit_date__lte=today, status="pending"
        ).count()
        verified = Visit.objects.filter(
            visit_date__gte=month_start, visit_date__lte=today, status="verified"
        ).count()
        total_work_hours = WorkLog.objects.filter(
            employee=request.user,
            start_time__date__gte=month_start,
            start_time__date__lte=today,
            is_active=False,
        ).aggregate(hours=Sum("total_duration"))["hours"]
        return Response(
            {
                "total_visits": total_visits,
                "pending": pending,
                "verified": verified,
                "total_work_hours": total_work_hours or 0,
            }
        )
