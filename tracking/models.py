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
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["date", "is_active"]),
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
            models.Index(fields=["workday", "recorded_at"]),
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


class DutySession(models.Model):
    """Employee duty shift (canonical session for duty start/end APIs)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="duty_sessions",
        db_index=True,
    )
    workday = models.OneToOneField(
        WorkDay,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duty_session",
    )
    date = models.DateField(db_index=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    auto_ended = models.BooleanField(default=False)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    class Meta:
        ordering = ["-start_time"]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["date", "is_active"]),
        ]

    def __str__(self):
        return f"Duty {self.user_id} | {self.date}"


class EmployeeLiveLocation(models.Model):
    """Latest GPS fix per employee (one row, update_or_create)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_location",
    )
    duty_session = models.ForeignKey(
        DutySession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="live_snapshots",
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    battery_level = models.IntegerField(null=True, blank=True)
    recorded_at = models.DateTimeField(db_index=True)
    gps_enabled = models.BooleanField(null=True, blank=True)
    location_permission_status = models.CharField(max_length=32, null=True, blank=True)
    background_tracking_enabled = models.BooleanField(null=True, blank=True)
    gps_reported_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["recorded_at"]),
        ]

    def __str__(self):
        return f"Live {self.user_id} @ {self.recorded_at}"


class EmployeeGpsState(models.Model):
    """Latest mobile-reported GPS permission / device state per employee."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gps_state",
    )
    gps_enabled = models.BooleanField(null=True, blank=True)
    location_permission_status = models.CharField(max_length=32, null=True, blank=True)
    background_tracking_enabled = models.BooleanField(null=True, blank=True)
    reported_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GPS state {self.user_id}"

class EmployeeRoutePoint(models.Model):
    """Filtered route history + permanent visit/farmer stops."""

    POINT_GPS = "gps"
    POINT_VISIT = "visit"
    POINT_FARMER = "farmer"
    POINT_TYPE_CHOICES = (
        (POINT_GPS, "GPS"),
        (POINT_VISIT, "Visit"),
        (POINT_FARMER, "Farmer"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="route_points",
        db_index=True,
    )
    duty_session = models.ForeignKey(
        DutySession,
        on_delete=models.CASCADE,
        related_name="route_points",
        db_index=True,
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField(db_index=True)
    point_type = models.CharField(
        max_length=10, choices=POINT_TYPE_CHOICES, default=POINT_GPS
    )
    visit_id = models.IntegerField(null=True, blank=True, db_index=True)
    farmer_id = models.IntegerField(null=True, blank=True, db_index=True)
    is_permanent = models.BooleanField(
        default=False,
        help_text="True for visit/farmer stops — never throttled or deduplicated away.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]
        indexes = [
            models.Index(fields=["user", "recorded_at"]),
            models.Index(fields=["duty_session", "recorded_at"]),
            models.Index(fields=["user", "point_type", "recorded_at"]),
        ]

    def __str__(self):
        return f"Route {self.user_id} @ {self.recorded_at}"
