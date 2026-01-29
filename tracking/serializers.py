from rest_framework import serializers
from django.utils import timezone

from .models import WorkDay, LocationLog, AvailabilityEvent
from notifications.utils import create_notification


class StartDaySerializer(serializers.Serializer):
    def save(self, **kwargs):
        user = self.context["request"].user

        # Prevent multiple active workdays
        if WorkDay.objects.filter(user=user, is_active=True).exists():
            raise serializers.ValidationError("Workday already started")

        workday = WorkDay.objects.create(
            user=user,
            date=timezone.now().date(),
            start_time=timezone.now(),
            is_active=True,
        )
        return workday


class EndDaySerializer(serializers.Serializer):
    def save(self, **kwargs):
        user = self.context["request"].user

        try:
            workday = WorkDay.objects.get(user=user, is_active=True)
        except WorkDay.DoesNotExist:
            raise serializers.ValidationError("No active workday found")

        workday.end_time = timezone.now()
        workday.is_active = False
        workday.save()

        return workday


class LocationLogCreateSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy = serializers.FloatField(required=False)
    recorded_at = serializers.DateTimeField()

    def save(self, **kwargs):
        user = self.context["request"].user

        # Admin cannot push location
        if user.is_staff:
            raise serializers.ValidationError("Admin cannot push location")

        try:
            workday = WorkDay.objects.get(user=user, is_active=True)
        except WorkDay.DoesNotExist:
            raise serializers.ValidationError("No active workday")

        location = LocationLog.objects.create(
            user=user,
            workday=workday,
            latitude=self.validated_data["latitude"],
            longitude=self.validated_data["longitude"],
            accuracy=self.validated_data.get("accuracy"),
            recorded_at=self.validated_data["recorded_at"],
        )
        return location


class LocationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationLog
        fields = [
            "latitude",
            "longitude",
            "accuracy",
            "recorded_at",
        ]


class HeartbeatSerializer(serializers.Serializer):
    gps_enabled = serializers.BooleanField()

    def save(self, **kwargs):
        user = self.context["request"].user

        if user.is_staff:
            raise serializers.ValidationError("Admin heartbeat not allowed")

        try:
            workday = WorkDay.objects.get(user=user, is_active=True)
        except WorkDay.DoesNotExist:
            raise serializers.ValidationError("No active workday")

        now = timezone.now()

        # ✅ UPDATE LAST HEARTBEAT (THIS WAS MISSING)
        workday.last_heartbeat = now
        workday.save(update_fields=["last_heartbeat"])

        # 🔹 GPS OFF
        if not self.validated_data["gps_enabled"]:
            AvailabilityEvent.objects.get_or_create(
                user=user,
                workday=workday,
                event_type="GPS_OFF",
                end_time__isnull=True,
                defaults={"start_time": now},
            )

        # 🔹 GPS ON
        else:
            AvailabilityEvent.objects.filter(
                user=user,
                workday=workday,
                event_type="GPS_OFF",
                end_time__isnull=True,
            ).update(end_time=now)

        return workday
