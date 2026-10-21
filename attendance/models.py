"""Shop attendance module — separate from Field Officer duty/tracking.

Attendance here means shop biometric (future) / kiosk check-in & check-out.
It is intentionally decoupled from tracking.DutySession / WorkDay.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q


class Shop(models.Model):
    """A physical shop / clinic location where attendance devices operate."""

    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=160)
    address = models.TextField(blank=True, default="")
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    geofence_radius_m = models.PositiveIntegerField(
        default=200,
        help_text="Optional soft geofence for kiosk check-ins (advisory only).",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} | {self.name}"


class AttendanceDevice(models.Model):
    """A registered attendance terminal (kiosk / future biometric scanner).

    Credentials are random one-time tokens. Only a SHA-256 hash is stored;
    the plaintext token is shown once at registration time.
    """

    DEVICE_KIOSK = "KIOSK"
    DEVICE_BIOMETRIC = "BIOMETRIC"
    DEVICE_TYPE_CHOICES = (
        (DEVICE_KIOSK, "Kiosk / test-mode tablet"),
        (DEVICE_BIOMETRIC, "Biometric scanner"),
    )

    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="attendance_devices",
    )
    device_uid = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Public device identifier sent in X-Device-Id header.",
    )
    name = models.CharField(max_length=120)
    device_type = models.CharField(
        max_length=16, choices=DEVICE_TYPE_CHOICES, default=DEVICE_KIOSK
    )
    token_hash = models.CharField(max_length=64, editable=False)
    token_prefix = models.CharField(
        max_length=12,
        editable=False,
        help_text="Non-secret prefix of the issued token for admin display.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_attendance_devices",
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["device_uid"]

    def __str__(self):
        return f"{self.device_uid} @ {self.shop.code}"


class AttendanceEmployee(models.Model):
    """Attendance-only employee identity.

    Shop employees who check in/out at attendance kiosks. They have NO Django
    user account, NO login credentials and NO Field Officer access. An
    optional `linked_profile` may reference an existing EmployeeProfile for
    reporting correlation only — it does not grant any authentication.
    """

    employee_code = models.CharField(
        max_length=32, unique=True, db_index=True,
        help_text="Unique human code shown on the selection screen/reports.",
    )
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=20, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    linked_profile = models.ForeignKey(
        "accounts.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_identities",
        help_text=(
            "Optional informational link to a Field Officer profile. "
            "Does NOT grant login or mobile access."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_attendance_employees",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_attendance_employees",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_code"]

    def __str__(self):
        return f"{self.employee_code} | {self.full_name}"


class EmployeeShopAssignment(models.Model):
    """Which attendance employees may record attendance at which shop."""

    employee = models.ForeignKey(
        AttendanceEmployee,
        on_delete=models.CASCADE,
        related_name="shop_assignments",
    )
    shift = models.ForeignKey(
        "Shift",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Optional default shift for this employee at this shop.",
    )
    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="employee_assignments",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_shop_assignments",
    )

    class Meta:
        ordering = ["shop", "employee"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "shop"],
                name="uniq_employee_shop_assignment",
            ),
        ]
        indexes = [
            models.Index(fields=["shop", "is_active"]),
            models.Index(fields=["employee", "is_active"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_code} -> {self.shop.code}"


class Shift(models.Model):
    """Shop shift window. Overnight shifts have end_time < start_time."""

    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shifts",
        help_text="Null = global fallback shift usable at any shop.",
    )
    name = models.CharField(max_length=80)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.PositiveIntegerField(default=15)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["shop", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "name"],
                name="uniq_shift_name_per_shop",
            ),
        ]

    @property
    def crosses_midnight(self) -> bool:
        return self.end_time <= self.start_time

    def __str__(self):
        return f"{self.name} {self.start_time}-{self.end_time}"


class AttendanceEvent(models.Model):
    """Immutable check-in / check-out record."""

    EVENT_CHECK_IN = "CHECK_IN"
    EVENT_CHECK_OUT = "CHECK_OUT"
    EVENT_TYPE_CHOICES = (
        (EVENT_CHECK_IN, "Check in"),
        (EVENT_CHECK_OUT, "Check out"),
    )

    METHOD_TEST_MANUAL = "TEST_MANUAL"
    METHOD_BIOMETRIC = "BIOMETRIC"
    METHOD_ADMIN_ADJUST = "ADMIN_ADJUST"
    VERIFICATION_METHOD_CHOICES = (
        (METHOD_TEST_MANUAL, "Test-mode manual selection"),
        (METHOD_BIOMETRIC, "Biometric verified"),
        (METHOD_ADMIN_ADJUST, "Admin adjustment"),
    )

    employee = models.ForeignKey(
        AttendanceEmployee,
        on_delete=models.PROTECT,
        related_name="attendance_events",
        db_index=True,
    )
    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="attendance_events",
    )
    device = models.ForeignKey(
        AttendanceDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_events",
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_events",
    )
    event_type = models.CharField(max_length=10, choices=EVENT_TYPE_CHOICES)
    occurred_at = models.DateTimeField(
        db_index=True,
        help_text="Authoritative server timestamp.",
    )
    client_event_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Client-generated idempotency key (unique per device).",
    )
    verification_method = models.CharField(
        max_length=16,
        choices=VERIFICATION_METHOD_CHOICES,
        default=METHOD_TEST_MANUAL,
        db_index=True,
    )
    is_test_mode = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True unless produced by a verified biometric adapter.",
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_attendance_events",
        help_text="Set only for admin adjustments.",
    )
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "shop", "occurred_at"]),
            models.Index(fields=["shop", "occurred_at"]),
            models.Index(fields=["verification_method", "occurred_at"]),
            models.Index(fields=["is_test_mode", "occurred_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "client_event_id"],
                condition=Q(client_event_id__isnull=False, device__isnull=False),
                name="uniq_attendance_event_device_client_id",
            ),
            models.CheckConstraint(
                check=Q(latitude__gte=-90) & Q(latitude__lte=90)
                | Q(latitude__isnull=True),
                name="attendance_event_latitude_range",
            ),
            models.CheckConstraint(
                check=Q(longitude__gte=-180) & Q(longitude__lte=180)
                | Q(longitude__isnull=True),
                name="attendance_event_longitude_range",
            ),
        ]

    def __str__(self):
        return (
            f"{self.event_type} {self.employee.employee_code} "
            f"@ {self.shop.code} {self.occurred_at}"
        )


class AttendanceDailySummary(models.Model):
    """Pre-computed per-employee per-shop per-day roll-up.

    `date` is the local (TIME_ZONE) calendar date of the first check-in of
    the pair; overnight sessions attribute worked time to the check-in date.
    """

    STATUS_PRESENT = "PRESENT"
    STATUS_HALF_DAY = "HALF_DAY"
    STATUS_INCOMPLETE = "INCOMPLETE"
    STATUS_CHOICES = (
        (STATUS_PRESENT, "Present"),
        (STATUS_HALF_DAY, "Half day"),
        (STATUS_INCOMPLETE, "Incomplete (missing checkout)"),
    )

    employee = models.ForeignKey(
        AttendanceEmployee,
        on_delete=models.CASCADE,
        related_name="attendance_daily_summaries",
    )
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name="attendance_daily_summaries",
    )
    date = models.DateField(db_index=True)
    first_check_in = models.DateTimeField(null=True, blank=True)
    last_check_out = models.DateTimeField(null=True, blank=True)
    worked_seconds = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_INCOMPLETE
    )
    has_open_session = models.BooleanField(
        default=False,
        help_text="True when a check-in on this date has no checkout yet.",
    )
    contains_test_events = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True when any contributing event is TEST_MANUAL.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "employee"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "shop", "date"],
                name="uniq_attendance_summary_emp_shop_date",
            ),
        ]
        indexes = [
            models.Index(fields=["shop", "date"]),
            models.Index(fields=["date", "contains_test_events"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_code} | {self.shop.code} | {self.date}"


class AttendanceAuditLog(models.Model):
    """Admin / device audit trail for the attendance module."""

    ACTION_CHOICES = (
        ("DEVICE_REGISTERED", "Device registered"),
        ("DEVICE_REVOKED", "Device revoked"),
        ("DEVICE_ROTATED", "Device token rotated"),
        ("SHOP_SAVED", "Shop created/updated"),
        ("ASSIGNMENT_SAVED", "Assignment created/updated"),
        ("SHIFT_SAVED", "Shift created/updated"),
        ("EMPLOYEE_SAVED", "Employee created/updated"),
        ("EMPLOYEE_DEACTIVATED", "Employee deactivated"),
        ("EMPLOYEE_ACTIVATED", "Employee activated"),
        ("EMPLOYEE_TRANSFERRED", "Employee transferred between shops"),
        ("CHECK_IN", "Check-in recorded"),
        ("CHECK_OUT", "Check-out recorded"),
        ("SUMMARY_REBUILT", "Summary rebuilt"),
        ("AUTH_FAILED", "Device authentication failed"),
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_audit_logs",
    )
    device = models.ForeignKey(
        AttendanceDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=32, blank=True, default="")
    entity_id = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.action} @ {self.created_at}"
