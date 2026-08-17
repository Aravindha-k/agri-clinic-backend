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
        indexes = [
            models.Index(fields=["is_active_employee"]),
            models.Index(fields=["is_active_employee", "district"]),
        ]

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


class AdminSecurityState(models.Model):
    """Login lockout and activity tracking for admin (staff) users."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_security",
    )
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Admin security states"

    def __str__(self):
        return f"AdminSecurity user_id={self.user_id}"


class AdminSession(models.Model):
    """Active admin panel sessions for monitoring and inactivity control."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_sessions",
    )
    session_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField()

    class Meta:
        ordering = ["-last_activity_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"AdminSession user_id={self.user_id} active={self.is_active}"


class EmployeeLocationAssignment(models.Model):
    """
    Administrative reference metadata only. Must not be used for authorization
    or operational scoping (farmer visibility, visits, tracking, auth, etc.).

    Links a field employee to District / Taluk / Village master rows for
    Admin-maintained territory reference. One row represents one assignment
    granularity level:
      - district-only: taluk=NULL, village=NULL
      - taluk-level:   village=NULL
      - village-level: all three set
    """

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="location_assignments",
    )
    district = models.ForeignKey(
        "masters.District",
        on_delete=models.PROTECT,
        related_name="employee_location_assignments",
    )
    taluk = models.ForeignKey(
        "masters.Taluk",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_location_assignments",
    )
    village = models.ForeignKey(
        "masters.Village",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_location_assignments",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employee_location_assignments",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_employee_location_assignments",
    )

    class Meta:
        ordering = ["employee", "district", "taluk", "village"]
        indexes = [
            models.Index(fields=["employee", "is_active"]),
            models.Index(fields=["district", "is_active"]),
            models.Index(fields=["taluk", "is_active"]),
            models.Index(fields=["village", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "district", "taluk", "village"],
                name="uniq_employee_location_assignment",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        parts = [self.district.name]
        if self.taluk_id:
            parts.append(self.taluk.name)
        if self.village_id:
            parts.append(self.village.name)
        return f"{self.employee.employee_id}: {' / '.join(parts)}"
