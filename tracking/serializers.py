from datetime import datetime, timezone as dt_timezone

from rest_framework import serializers
from django.utils import timezone

from .models import WorkDay, LocationLog, AvailabilityEvent
from .workday_utils import expire_overlong_workdays_for_user
from notifications.utils import create_notification


class FlexibleDateTimeField(serializers.DateTimeField):
    """DateTimeField that also accepts Unix timestamps (seconds or milliseconds)."""

    def to_internal_value(self, value):
        if isinstance(value, (int, float)):
            if value > 1e12:
                value = value / 1000
            return datetime.fromtimestamp(value, tz=dt_timezone.utc)
        # Handle string-encoded numeric timestamps (e.g. "1741609160")
        if isinstance(value, str):
            try:
                numeric = float(value)
                if numeric > 1e8:  # looks like a Unix timestamp
                    if numeric > 1e12:
                        numeric = numeric / 1000
                    return datetime.fromtimestamp(numeric, tz=dt_timezone.utc)
            except ValueError:
                pass
        return super().to_internal_value(value)


class FlexibleDecimalField(serializers.DecimalField):
    """DecimalField that normalizes trailing zeros before validation."""

    def to_internal_value(self, value):
        if isinstance(value, str):
            try:
                from decimal import Decimal

                value = str(Decimal(value).normalize())
            except Exception:
                pass
        return super().to_internal_value(value)


class StartDaySerializer(serializers.Serializer):
    def save(self, **kwargs):
        user = self.context["request"].user

        expire_overlong_workdays_for_user(user)

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

        expire_overlong_workdays_for_user(user)

        try:
            workday = WorkDay.objects.get(user=user, is_active=True)
        except WorkDay.DoesNotExist:
            raise serializers.ValidationError("No active workday found")

        workday.end_time = timezone.now()
        workday.is_active = False
        workday.save()

        return workday


class LocationLogCreateSerializer(serializers.Serializer):
    latitude = FlexibleDecimalField(max_digits=9, decimal_places=6)
    longitude = FlexibleDecimalField(max_digits=9, decimal_places=6)
    accuracy = serializers.FloatField(required=False)
    speed = serializers.FloatField(required=False)
    heading = serializers.FloatField(required=False)
    recorded_at = FlexibleDateTimeField(required=False)
    captured_at = FlexibleDateTimeField(required=False)
    battery_level = serializers.IntegerField(required=False, min_value=0, max_value=100)
    network_type = serializers.CharField(required=False, max_length=20)
    device_model = serializers.CharField(required=False, max_length=100)
    app_version = serializers.CharField(required=False, max_length=20)

    def save(self, **kwargs):
        user = self.context["request"].user

        # Admin cannot push location
        if user.is_staff:
            raise serializers.ValidationError("Admin cannot push location")

        expire_overlong_workdays_for_user(user)

        workday = (
            WorkDay.objects.filter(user=user, is_active=True)
            .order_by("-start_time")
            .first()
        )
        if not workday:
            raise serializers.ValidationError("No active workday")

        recorded_at = (
            self.validated_data.get("captured_at")
            or self.validated_data.get("recorded_at")
            or timezone.now()
        )

        location = LocationLog.objects.create(
            user=user,
            workday=workday,
            latitude=self.validated_data["latitude"],
            longitude=self.validated_data["longitude"],
            accuracy=self.validated_data.get("accuracy"),
            speed=self.validated_data.get("speed"),
            heading=self.validated_data.get("heading"),
            battery_level=self.validated_data.get("battery_level"),
            network_type=self.validated_data.get("network_type"),
            device_model=self.validated_data.get("device_model"),
            app_version=self.validated_data.get("app_version"),
            recorded_at=recorded_at,
        )
        from .services import refresh_workday_live_state

        refresh_workday_live_state(
            user=user,
            workday=workday,
            latitude=float(location.latitude),
            longitude=float(location.longitude),
            accuracy=location.accuracy,
            battery_level=location.battery_level,
            recorded_at=recorded_at,
        )
        return location


class BulkLocationPointSerializer(serializers.Serializer):
    """Single point inside a bulk push payload."""

    latitude = FlexibleDecimalField(max_digits=9, decimal_places=6)
    longitude = FlexibleDecimalField(max_digits=9, decimal_places=6)
    accuracy = serializers.FloatField(required=False)
    speed = serializers.FloatField(required=False)
    heading = serializers.FloatField(required=False)
    recorded_at = FlexibleDateTimeField(required=False)
    captured_at = FlexibleDateTimeField(required=False)
    battery_level = serializers.IntegerField(required=False, min_value=0, max_value=100)
    network_type = serializers.CharField(required=False, max_length=20)


class BulkLocationPushSerializer(serializers.Serializer):
    """
    Accepts a list of GPS points for offline/batch push.
    Also accepts optional device-level fields sent once per request.
    """

    locations = BulkLocationPointSerializer(many=True)
    device_model = serializers.CharField(required=False, max_length=100)
    app_version = serializers.CharField(required=False, max_length=20)


class LocationLogSerializer(serializers.ModelSerializer):
    captured_at = serializers.DateTimeField(source="recorded_at", read_only=True)

    class Meta:
        model = LocationLog
        fields = [
            "id",
            "latitude",
            "longitude",
            "accuracy",
            "speed",
            "heading",
            "battery_level",
            "is_suspicious",
            "recorded_at",
            "captured_at",
            "created_at",
        ]


class HeartbeatSerializer(serializers.Serializer):
    gps_enabled = serializers.BooleanField()

    def save(self, **kwargs):
        user = self.context["request"].user

        if user.is_staff:
            raise serializers.ValidationError("Admin heartbeat not allowed")

        expire_overlong_workdays_for_user(user)

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
