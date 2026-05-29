from django.conf import settings
from django.db import models


class WorkDay(models.Model):
    """
    One work session per employee per day
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workdays",
    )

    date = models.DateField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    auto_ended = models.BooleanField(
        default=False,
        help_text="Whether this workday was automatically ended due to time limit",
    )

    last_heartbeat = models.DateTimeField(null=True, blank=True)

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Start latitude",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Start longitude",
    )

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.user.username} | {self.date}"


class LocationLog(models.Model):
    """
    Continuous GPS log (route tracking)
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="location_logs",
    )

    workday = models.ForeignKey(
        WorkDay,
        on_delete=models.CASCADE,
        related_name="locations",
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(
        null=True,
        blank=True,
        help_text="Speed in km/h when provided by the device",
    )
    heading = models.FloatField(
        null=True,
        blank=True,
        help_text="Heading/bearing in degrees when provided by the device",
    )

    # Device / context fields (mobile-ready)
    battery_level = models.IntegerField(null=True, blank=True)
    network_type = models.CharField(max_length=20, null=True, blank=True)
    device_model = models.CharField(max_length=100, null=True, blank=True)
    app_version = models.CharField(max_length=20, null=True, blank=True)
    is_suspicious = models.BooleanField(default=False)

    recorded_at = models.DateTimeField()

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Server time when this point was stored",
    )

    class Meta:
        ordering = ["recorded_at"]
        indexes = [
            models.Index(fields=["user", "recorded_at"]),
            models.Index(fields=["recorded_at"]),
        ]


class EmployeeDailySummary(models.Model):
    """
    Pre-computed daily summary per employee — rebuilt at end-of-day or on demand.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_summaries",
    )
    date = models.DateField()
    total_distance_km = models.FloatField(default=0)
    total_duration_seconds = models.IntegerField(default=0)
    total_points = models.IntegerField(default=0)
    gps_issues_count = models.IntegerField(default=0)
    suspicious_points = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.user.username} | {self.date} | {self.total_distance_km} km"


class AvailabilityEvent(models.Model):
    """
    Employee availability state changes
    """

    EVENT_TYPES = (
        ("GPS_OFF", "GPS Off"),
        ("OFFLINE", "Offline"),
        ("APP_OFF", "App Closed"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_events",
    )

    workday = models.ForeignKey(
        WorkDay,
        on_delete=models.CASCADE,
        related_name="availability_events",
    )

    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self):
        return f"{self.user.username} | {self.event_type}"
