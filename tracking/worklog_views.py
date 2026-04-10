from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from drf_spectacular.utils import extend_schema

from .worklog import WorkLog
from .worklog_serializers import WorkLogSerializer
from utils.response import success_response, error_response
from utils.schema import SIMPLE_SUCCESS, error_schema


@extend_schema(
    tags=["Tracking"],
    summary="Start work session (WorkLog)",
    description="Starts a new work log session for the employee. Only one active session is allowed at a time.",
    request=None,
    responses={200: WorkLogSerializer, 400: error_schema("WorkLogAlreadyActive")},
)
class WorkLogStartAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee = request.user
        # Only one active session per employee
        if WorkLog.objects.filter(employee=employee, is_active=True).exists():
            return error_response(message="Active work session already exists.")
        log = WorkLog.objects.create(
            employee=employee,
            start_time=timezone.now(),
            is_active=True,
        )
        return success_response(data=WorkLogSerializer(log).data)


@extend_schema(
    tags=["Tracking"],
    summary="End work session (WorkLog)",
    description="Ends the current active work log session and records total duration.",
    request=None,
    responses={200: WorkLogSerializer, 400: error_schema("WorkLogNotFound")},
)
class WorkLogEndAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee = request.user
        try:
            log = WorkLog.objects.get(employee=employee, is_active=True)
        except WorkLog.DoesNotExist:
            return error_response(message="No active work session found.")
        log.end_time = timezone.now()
        log.total_duration = log.end_time - log.start_time
        log.is_active = False
        log.save()
        return success_response(data=WorkLogSerializer(log).data)


@extend_schema(
    tags=["Tracking"],
    summary="Current work session status (WorkLog)",
    description="Returns the current active work log session if one exists.",
    responses={200: WorkLogSerializer},
)
class WorkLogStatusAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = request.user
        log = WorkLog.objects.filter(employee=employee, is_active=True).first()
        return success_response(data=WorkLogSerializer(log).data if log else None)


@extend_schema(
    tags=["Tracking"],
    summary="Work session history (WorkLog)",
    description="Returns all past work log sessions for the employee, ordered by most recent.",
    responses={200: WorkLogSerializer(many=True)},
)
class WorkLogHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = request.user
        logs = WorkLog.objects.filter(employee=employee).order_by("-start_time")
        return success_response(data=WorkLogSerializer(logs, many=True).data)
