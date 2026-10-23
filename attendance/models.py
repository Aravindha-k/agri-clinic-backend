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
    area = models.CharField(max_length=160, blank=True, default="")
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
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the shop is archived (soft-delete). History kept.",
    )
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_attendance_shops",
    )
    archive_reason = models.CharField(max_length=160, blank=True, default="")
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


class DevicePairingCode(models.Model):
    """One-time, short-lived code that activates a pre-registered device.

    Only a keyed HMAC-SHA256 hash of the 6-digit code is stored. The device
    itself is
    created inactive at code-generation time and becomes usable only after a
    successful redemption, which also issues its real credential token.
    """

    MAX_ATTEMPTS = 5
    TTL_MINUTES = 5
    MAX_ACTIVE_PER_SHOP = 1  # issuing a new code expires the previous one

    device = models.ForeignKey(
        AttendanceDevice,
        on_delete=models.CASCADE,
        related_name="pairing_codes",
    )
    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    code_prefix = models.CharField(
        max_length=2,
        editable=False,
        help_text="First 2 digits, non-secret, for admin correlation.",
    )
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pairing_codes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pairing code for {self.device.device_uid} (exp {self.expires_at})"


class FaceEnrollment(models.Model):
    """Authorization + status record for employee face enrollment on a kiosk.

    Stores METADATA ONLY — face images and embeddings never leave the kiosk;
    they stay encrypted on-device (MobileFaceNet 1:N). A row means an
    administrator authorized enrollment for (employee, device); completion is
    reported back by the device itself. Revoked/replaced rows authorize
    nothing.
    """

    STATUS_PENDING = "PENDING"      # admin authorized; awaiting samples
    STATUS_ACTIVE = "ACTIVE"        # device confirmed enrollment complete
    STATUS_REVOKED = "REVOKED"
    STATUS_REPLACED = "REPLACED"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending (authorized, not enrolled)"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_REVOKED, "Revoked"),
        (STATUS_REPLACED, "Replaced"),
    )

    employee = models.ForeignKey(
        "AttendanceEmployee",
        on_delete=models.PROTECT,
        related_name="face_enrollments",
    )
    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="face_enrollments",
    )
    device = models.ForeignKey(
        AttendanceDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="face_enrollments",
        help_text="Kiosk this enrollment is bound to. Null = invalid.",
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    consent_recorded = models.BooleanField(
        default=False,
        help_text="Employee consent to face enrollment was captured.",
    )
    consent_at = models.DateTimeField(null=True, blank=True)
    sample_count = models.PositiveIntegerField(
        default=0, help_text="Face samples captured on the kiosk."
    )
    enrolled_at = models.DateTimeField(
        null=True, blank=True, help_text="Set when the device reports completion."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_face_enrollments",
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_face_enrollments",
    )
    revoke_reason = models.CharField(max_length=160, blank=True, default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "device"],
                condition=Q(status__in=["PENDING", "ACTIVE"]),
                name="uniq_face_enrollment_live_per_device",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["device", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.employee.employee_code} face @ "
            f"{self.device_id and 'dev-' + str(self.device_id)} [{self.status}]"
        )


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
        ("PAIRING_CODE_ISSUED", "Pairing code issued"),
        ("DEVICE_PAIRED", "Device paired"),
        ("PAIRING_FAILED", "Pairing attempt failed"),
        ("DEVICE_DELETED", "Device deleted"),
        ("SHOP_ARCHIVED", "Shop archived"),
        ("SHOP_DELETED", "Shop deleted"),
        ("ENROLLMENT_AUTHORIZED", "Face enrollment authorized"),
        ("ENROLLMENT_COMPLETED", "Face enrollment completed on device"),
        ("ENROLLMENT_REVOKED", "Face enrollment revoked"),
        ("ENROLLMENT_REPLACED", "Face enrollment replaced"),
        ("FACE_VERIFY_REJECTED", "Face verification rejected"),
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
