from django.conf import settings
from django.db import models


class WorkDay(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # ✅ ADD THIS
    last_heartbeat = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.date}"


class LocationLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    workday = models.ForeignKey(WorkDay, on_delete=models.CASCADE)

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy = models.FloatField(null=True, blank=True)

    recorded_at = models.DateTimeField()


class AvailabilityEvent(models.Model):
    EVENT_TYPES = (
        ("GPS_OFF", "GPS Off"),
        ("OFFLINE", "Offline"),
        ("APP_OFF", "App Off"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    workday = models.ForeignKey(WorkDay, on_delete=models.CASCADE)

    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.event_type}"


class LocationPing(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="location_pings",
    )

    latitude = models.FloatField()
    longitude = models.FloatField()

    accuracy = models.FloatField(default=0)

    # ✅ Visit stop marker (only few points)
    is_visit = models.BooleanField(default=False)

    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.latitude},{self.longitude}"
