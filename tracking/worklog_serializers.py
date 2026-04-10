from rest_framework import serializers
from .worklog import WorkLog


class WorkLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkLog
        fields = [
            "id",
            "employee",
            "start_time",
            "end_time",
            "total_duration",
            "is_active",
        ]
        read_only_fields = ("id", "employee", "total_duration", "is_active")
