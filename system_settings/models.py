from django.db import models


class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key


class SystemConfig(models.Model):
    """
    Single-row configuration for tracking / GPS thresholds.
    Always use SystemConfig.load() to fetch the singleton.
    """

    heartbeat_timeout_minutes = models.IntegerField(default=5)
    gps_accuracy_limit = models.IntegerField(default=50)
    gps_jump_limit_km = models.FloatField(default=5.0)
    tracking_stale_minutes = models.IntegerField(default=10)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Config"
        verbose_name_plural = "System Config"

    def __str__(self):
        return "SystemConfig (singleton)"

    def save(self, *args, **kwargs):
        # Enforce single-row: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
