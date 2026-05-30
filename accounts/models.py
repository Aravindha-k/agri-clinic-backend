import uuid

from django.db import models
from django.conf import settings


class EmployeeProfile(models.Model):
    """
    Enterprise employee profile.
    One-to-one with auth user.
    """

    ROLE_CHOICES = (
        ("FieldAgent", "Field Agent"),
        ("Supervisor", "Supervisor"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_profile",
    )

    employee_id = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
    )

    phone = models.CharField(max_length=15)

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="FieldAgent",
    )

    district = models.ForeignKey(
        "masters.District",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    village = models.ForeignKey(
        "masters.Village",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    is_active_employee = models.BooleanField(default=True)

    can_login = models.BooleanField(default=True)

    profile_photo = models.ImageField(
        upload_to="employee_photos/%Y/%m/",
        null=True,
        blank=True,
    )

    profile_photo_updated_at = models.DateTimeField(null=True, blank=True)

    mobile_session_version = models.PositiveIntegerField(default=0)
    active_device_id = models.CharField(max_length=64, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.employee_id} | {self.user.username}"


class EmployeeDeviceSession(models.Model):
    """
    One active mobile device session per employee.
    Latest login invalidates previous sessions (latest wins).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_sessions",
    )
    session_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    active_device_id = models.CharField(max_length=64, null=True, blank=True)
    session_version = models.PositiveIntegerField(default=1)
    device_name = models.CharField(max_length=120, null=True, blank=True)
    device_model = models.CharField(max_length=120, null=True, blank=True)
    platform = models.CharField(max_length=40, null=True, blank=True)
    app_version = models.CharField(max_length=40, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    last_login_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_login_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user_id} | {self.session_key} | active={self.is_active}"
