"""
Fresh operational-data reset for Kavya Agri Clinic.

Default is dry-run. Destructive execution requires --execute plus an exact
confirmation phrase. Employees, users, auth, and reusable masters are kept.
Physical uploaded files are never deleted by this module.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Model, ProtectedError, Q, QuerySet

CONFIRM_PHRASE = "RESET KAVYA OPERATIONAL DATA"

# Auth / employees / reusable crop-problem config / security history.
PRESERVE_MODELS = (
    "auth.User",
    "auth.Group",
    "auth.Permission",
    "accounts.EmployeeProfile",
    "accounts.EmployeeDeviceSession",
    "accounts.AdminSecurityState",
    "accounts.AdminSession",
    "masters.Crop",
    "masters.ProblemCategory",
    "masters.ProblemMaster",
    "masters.CropProblem",
    "system_settings.SystemConfig",
    "system_settings.SystemSetting",
    "audit_logs.AuditLog",
    "admin.LogEntry",
    "sessions.Session",
    "contenttypes.ContentType",
    "token_blacklist.OutstandingToken",
    "token_blacklist.BlacklistedToken",
    "django_celery_results.TaskResult",
    "django_celery_results.GroupResult",
    "django_celery_results.ChordCounter",
)

# Display name, model label — deletion order (children before PROTECT parents).
DELETE_MODELS: tuple[tuple[str, str], ...] = (
    ("Recommendation", "masters.Recommendation"),
    ("CropIssue", "masters.CropIssue"),
    ("VisitMedia", "visits.VisitMedia"),
    ("VisitAttachment", "visits.VisitAttachment"),
    ("Visit", "visits.Visit"),
    ("FieldCrop", "masters.FieldCrop"),
    ("FarmerField", "masters.FarmerField"),
    ("FarmerActivity", "masters.FarmerActivity"),
    ("Farmer", "masters.Farmer"),
    ("EmployeeLocationAssignment", "accounts.EmployeeLocationAssignment"),
    ("Notification", "notifications.Notification"),
    ("Report", "reports.Report"),
    ("EmployeeRoutePoint", "tracking.EmployeeRoutePoint"),
    ("LocationLog", "tracking.LocationLog"),
    ("AvailabilityEvent", "tracking.AvailabilityEvent"),
    ("EmployeeDailySummary", "tracking.EmployeeDailySummary"),
    ("WorkLog", "tracking.WorkLog"),
    ("EmployeeLiveLocation", "tracking.EmployeeLiveLocation"),
    ("EmployeeGpsState", "tracking.EmployeeGpsState"),
    ("DutySession", "tracking.DutySession"),
    ("WorkDay", "tracking.WorkDay"),
    ("Village", "masters.Village"),
    ("Taluk", "masters.Taluk"),
    ("District", "masters.District"),
)

# FileFields on rows that will be deleted. Files are reported, not removed.
MEDIA_FIELDS: tuple[tuple[str, str], ...] = (
    ("visits.VisitMedia", "file"),
    ("visits.VisitAttachment", "file"),
    ("masters.Farmer", "profile_photo"),
    ("reports.Report", "file"),
)

# Employee photos stay with preserved EmployeeProfile rows.
PRESERVED_MEDIA_FIELDS: tuple[tuple[str, str], ...] = (
    ("accounts.EmployeeProfile", "profile_photo"),
)

UNAVOIDABLE_DEPENDENCIES = (
    "AuditLog.object_id / metadata may still name deleted Farmer/Visit/Village PKs. "
    "Rows are preserved; IDs become historical references.",
    "admin.LogEntry.object_id may still name deleted objects. Rows are preserved.",
    "EmployeeRoutePoint.visit_id / farmer_id are integer IDs (not FKs); those rows "
    "are deleted with tracking history so they do not dangle.",
    "FarmerActivity.reference_id is an integer ID; those rows are deleted with farmers.",
    "EmployeeProfile.district / village are SET_NULL before location-master delete "
    "(deprecated location columns only; employee identity is unchanged).",
)


@dataclass
class MediaReport:
    model_label: str
    field_name: str
    row_count_with_file: int
    sample_names: list[str]
    storage: str
    preserved: bool = False


@dataclass
class ResetPlan:
    preserve: OrderedDict[str, int] = field(default_factory=OrderedDict)
    delete: OrderedDict[str, int] = field(default_factory=OrderedDict)
    null_updates: OrderedDict[str, int] = field(default_factory=OrderedDict)
    media: list[MediaReport] = field(default_factory=list)
    remaining_location_refs: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    protect_blockers: list[str] = field(default_factory=list)


def is_production_env() -> bool:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if app_env in {"prod", "production", "render", "staging", "aws"}:
        return True
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


def _storage_label() -> str:
    if getattr(settings, "USE_S3", False):
        return "S3 (storages.backends.s3boto3.S3Boto3Storage)"
    return "local filesystem (django.core.files.storage.FileSystemStorage)"


def _get_model(label: str) -> type[Model] | None:
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def _count(model: type[Model] | None) -> int:
    if model is None:
        return 0
    return model.objects.count()


def _worklog_model() -> type[Model] | None:
    try:
        from tracking.worklog import WorkLog

        return WorkLog
    except Exception:
        return _get_model("tracking.WorkLog")


def _file_stats(label: str, field_name: str, *, preserved: bool = False) -> MediaReport:
    model = _get_model(label)
    samples: list[str] = []
    count = 0
    if model is not None:
        lookup = {f"{field_name}__isnull": False}
        qs = model.objects.exclude(**{field_name: ""}).filter(**lookup)
        count = qs.count()
        for obj in qs.only("pk", field_name)[:5]:
            f = getattr(obj, field_name, None)
            name = getattr(f, "name", "") or ""
            if name:
                samples.append(name)
    return MediaReport(
        model_label=label,
        field_name=field_name,
        row_count_with_file=count,
        sample_names=samples,
        storage=_storage_label(),
        preserved=preserved,
    )


def _on_delete_name(field) -> str:
    remote = getattr(field, "remote_field", None)
    on_delete = getattr(remote, "on_delete", None) if remote else None
    return getattr(on_delete, "__name__", str(on_delete or ""))


def _reverse_fk_counts(target: type[Model]) -> list[str]:
    """Non-zero reverse relations pointing at target (excluding itself)."""
    rows: list[str] = []
    for rel in target._meta.get_fields():
        if not getattr(rel, "is_relation", False) or not getattr(rel, "auto_created", False):
            continue
        related_model = getattr(rel, "related_model", None)
        if related_model is None or related_model is target:
            continue
        accessor = rel.get_accessor_name()
        if not accessor:
            continue
        field = getattr(rel, "field", None)
        if field is None:
            continue
        try:
            n = related_model.objects.exclude(**{f"{field.name}_id": None}).count()
        except Exception:
            continue
        if n:
            rows.append(
                f"{related_model._meta.label}.{field.name} "
                f"n={n} on_delete={_on_delete_name(field)}"
            )
    return rows


def _m2m_through_count(from_label: str, field_name: str) -> int:
    model = _get_model(from_label)
    if model is None:
        return 0
    field = model._meta.get_field(field_name)
    through = getattr(field, "remote_field", None)
    through_model = getattr(through, "through", None) if through else None
    if through_model is None:
        return 0
    return through_model.objects.count()


def critical_counts() -> OrderedDict[str, int]:
    User = get_user_model()
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    counts: OrderedDict[str, int] = OrderedDict()
    counts["Users"] = User.objects.count()
    counts["Superusers"] = User.objects.filter(is_superuser=True).count()
    counts["EmployeeProfiles"] = EmployeeProfile.objects.count()
    counts["Active Employees"] = EmployeeProfile.objects.filter(
        is_active_employee=True
    ).count()
    counts["Farmer"] = _count(_get_model("masters.Farmer"))
    counts["Visit"] = _count(_get_model("visits.Visit"))
    counts["Village"] = _count(_get_model("masters.Village"))
    counts["District"] = _count(_get_model("masters.District"))
    counts["Taluk"] = _count(_get_model("masters.Taluk"))
    counts["EmployeeLocationAssignment"] = _count(
        _get_model("accounts.EmployeeLocationAssignment")
    )
    return counts


def _collect_unclassified(known_labels: set[str]) -> list[str]:
    rows: list[str] = []
    skip_apps = {
        "admin",
        "auth",
        "contenttypes",
        "sessions",
        "messages",
        "staticfiles",
        "token_blacklist",
        "django_celery_results",
        "rest_framework",
        "corsheaders",
        "django_filters",
        "drf_spectacular",
        "storages",
    }
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        label = model._meta.label
        if label in known_labels:
            continue
        if model._meta.app_label in skip_apps:
            continue
        if model._meta.auto_created:
            continue
        rows.append(label)
    return sorted(rows)


def collect_plan() -> ResetPlan:
    """
    Read-only inventory. Wrapped in a rolled-back atomic block so any accidental
    write during planning cannot persist.
    """
    with transaction.atomic():
        plan = _build_plan()
        transaction.set_rollback(True)
        return plan


def _build_plan() -> ResetPlan:
    User = get_user_model()
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    Group = _get_model("auth.Group")
    Permission = _get_model("auth.Permission")
    plan = ResetPlan()

    plan.preserve["Users"] = User.objects.count()
    plan.preserve["Superusers"] = User.objects.filter(is_superuser=True).count()
    plan.preserve["Admins (is_staff)"] = User.objects.filter(is_staff=True).count()
    plan.preserve["EmployeeProfiles"] = EmployeeProfile.objects.count()
    plan.preserve["Active Employees"] = EmployeeProfile.objects.filter(
        is_active_employee=True
    ).count()
    plan.preserve["Field employees (FieldAgent)"] = EmployeeProfile.objects.filter(
        role="FieldAgent"
    ).count()
    plan.preserve["Groups"] = _count(Group)
    plan.preserve["Permissions"] = _count(Permission)
    plan.preserve["Employee device sessions"] = _count(
        _get_model("accounts.EmployeeDeviceSession")
    )
    plan.preserve["Admin sessions"] = _count(_get_model("accounts.AdminSession"))
    plan.preserve["Admin security states"] = _count(
        _get_model("accounts.AdminSecurityState")
    )
    plan.preserve["Crops"] = _count(_get_model("masters.Crop"))
    plan.preserve["Problem Categories"] = _count(_get_model("masters.ProblemCategory"))
    plan.preserve["Problem Items"] = _count(_get_model("masters.ProblemMaster"))
    plan.preserve["Crop↔problem mappings"] = _count(_get_model("masters.CropProblem"))
    plan.preserve["SystemConfig"] = _count(_get_model("system_settings.SystemConfig"))
    plan.preserve["SystemSetting"] = _count(_get_model("system_settings.SystemSetting"))
    plan.preserve["Audit logs"] = _count(_get_model("audit_logs.AuditLog"))
    plan.preserve["Admin log entries"] = _count(_get_model("admin.LogEntry"))
    plan.preserve["Django sessions"] = _count(_get_model("sessions.Session"))
    plan.preserve["JWT outstanding tokens"] = _count(
        _get_model("token_blacklist.OutstandingToken")
    )
    plan.preserve["JWT blacklisted tokens"] = _count(
        _get_model("token_blacklist.BlacklistedToken")
    )

    for name, label in DELETE_MODELS:
        if label == "tracking.WorkLog":
            plan.delete[name] = _count(_worklog_model())
        else:
            plan.delete[name] = _count(_get_model(label))
    plan.delete["Visit problem-item links (M2M)"] = _m2m_through_count(
        "visits.Visit", "problem_items"
    )

    plan.null_updates["EmployeeProfile.district/village → NULL"] = (
        EmployeeProfile.objects.filter(
            Q(district_id__isnull=False) | Q(village_id__isnull=False)
        ).count()
    )

    for label, field_name in MEDIA_FIELDS:
        plan.media.append(_file_stats(label, field_name, preserved=False))
    for label, field_name in PRESERVED_MEDIA_FIELDS:
        plan.media.append(_file_stats(label, field_name, preserved=True))

    for loc_label in ("masters.District", "masters.Taluk", "masters.Village"):
        model = _get_model(loc_label)
        if model is not None:
            plan.remaining_location_refs.extend(
                f"{loc_label}: {row}" for row in _reverse_fk_counts(model)
            )

    known = set(PRESERVE_MODELS) | {label for _, label in DELETE_MODELS}
    plan.unclassified = _collect_unclassified(known)

    protect_labels = ("masters.Village", "masters.Taluk", "masters.District")
    for loc_label in protect_labels:
        model = _get_model(loc_label)
        if model is None:
            continue
        for rel in model._meta.get_fields():
            if not getattr(rel, "auto_created", False) or not getattr(rel, "field", None):
                continue
            field = rel.field
            if _on_delete_name(field) != "PROTECT":
                continue
            related = rel.related_model
            if related is None:
                continue
            related_label = related._meta.label
            if related_label in known and related_label not in {
                label for _, label in DELETE_MODELS
            }:
                plan.protect_blockers.append(
                    f"{related_label}.{field.name} PROTECT → {loc_label}"
                )
    return plan


def _qs(label: str) -> QuerySet:
    if label == "tracking.WorkLog":
        model = _worklog_model()
    else:
        model = _get_model(label)
    if model is None:
        return apps.get_model("auth", "User").objects.none()
    return model.objects.all()


def execute_reset() -> dict[str, int]:
    """
    Delete operational rows in FK-safe order inside one transaction.
    Does not delete users, employee profiles, auth, or reusable masters.
    Does not delete physical media files.
    """
    from accounts.models import EmployeeProfile

    deleted: dict[str, int] = {}

    def wipe(name: str, qs: QuerySet) -> None:
        n, _ = qs.delete()
        deleted[name] = n

    with transaction.atomic():
        wipe("recommendations", _qs("masters.Recommendation"))
        wipe("crop_issues", _qs("masters.CropIssue"))
        wipe("visit_media", _qs("visits.VisitMedia"))
        wipe("visit_attachments", _qs("visits.VisitAttachment"))
        wipe("visits", _qs("visits.Visit"))
        wipe("field_crops", _qs("masters.FieldCrop"))
        wipe("farmer_fields", _qs("masters.FarmerField"))
        wipe("farmer_activity", _qs("masters.FarmerActivity"))
        wipe("farmers", _qs("masters.Farmer"))
        wipe("employee_location_assignments", _qs("accounts.EmployeeLocationAssignment"))

        n_district = EmployeeProfile.objects.exclude(district_id=None).update(
            district=None
        )
        n_village = EmployeeProfile.objects.exclude(village_id=None).update(
            village=None
        )
        deleted["employeeprofile_location_nulls"] = n_district + n_village

        wipe("notifications", _qs("notifications.Notification"))
        wipe("reports", _qs("reports.Report"))
        wipe("route_points", _qs("tracking.EmployeeRoutePoint"))
        wipe("location_logs", _qs("tracking.LocationLog"))
        wipe("availability_events", _qs("tracking.AvailabilityEvent"))
        wipe("daily_summaries", _qs("tracking.EmployeeDailySummary"))
        worklog = _worklog_model()
        if worklog is not None:
            wipe("work_logs", worklog.objects.all())
        wipe("live_locations", _qs("tracking.EmployeeLiveLocation"))
        wipe("gps_state", _qs("tracking.EmployeeGpsState"))
        wipe("duty_sessions", _qs("tracking.DutySession"))
        wipe("workdays", _qs("tracking.WorkDay"))

        try:
            wipe("villages", _qs("masters.Village"))
            wipe("taluks", _qs("masters.Taluk"))
            wipe("districts", _qs("masters.District"))
        except ProtectedError as exc:
            raise ProtectedError(
                "Location master delete blocked by remaining protected FKs. "
                "Operational children must be removed first.",
                exc.protected_objects,
            ) from exc

    return deleted


def plans_equal(a: ResetPlan, b: ResetPlan) -> bool:
    return (
        list(a.preserve.items()) == list(b.preserve.items())
        and list(a.delete.items()) == list(b.delete.items())
        and list(a.null_updates.items()) == list(b.null_updates.items())
    )


def format_plan(plan: ResetPlan, *, dry_run: bool) -> str:
    lines = []
    mode = "DRY RUN — no rows will be deleted." if dry_run else "EXECUTE — destructive reset."
    lines.append(mode)
    lines.append("")
    lines.append("--- PRESERVE ---")
    for name, n in plan.preserve.items():
        lines.append(f"{name}: {n}")
    lines.append("")
    lines.append("--- DELETE ---")
    for name, n in plan.delete.items():
        lines.append(f"{name}: {n}")
    lines.append("")
    lines.append("WILL NULL (keep employee row)")
    for name, n in plan.null_updates.items():
        lines.append(f"  {name}: {n}")
    lines.append("")
    lines.append("PHYSICAL MEDIA: NOT DELETED")
    lines.append(f"  Storage: {_storage_label()}")
    for item in plan.media:
        flag = "PRESERVED (employee photos)" if item.preserved else "DB row may be reset; file kept"
        lines.append(
            f"  {item.model_label}.{item.field_name}: {item.row_count_with_file} files ({flag})"
        )
        for sample in item.sample_names:
            lines.append(f"    sample: {sample}")
    lines.append("  Orphan file cleanup must be a separate, explicit step after a successful DB reset.")
    lines.append("")
    lines.append("UNAVOIDABLE DEPENDENCIES (schema allows preserve)")
    for row in UNAVOIDABLE_DEPENDENCIES:
        lines.append(f"  - {row}")
    lines.append("")
    if plan.remaining_location_refs:
        lines.append("CURRENT LOCATION REVERSE-FK SNAPSHOT (pre-reset)")
        for row in plan.remaining_location_refs:
            lines.append(f"  {row}")
        lines.append("")
    if plan.protect_blockers:
        lines.append("PROTECT RELATIONS FROM PRESERVED MODELS (must not remain)")
        for row in plan.protect_blockers:
            lines.append(f"  {row}")
        lines.append("")
    if plan.unclassified:
        lines.append("UNCLASSIFIED MODELS (not in preserve/delete lists)")
        for row in plan.unclassified:
            lines.append(f"  {row}")
        lines.append("")
    else:
        lines.append("UNCLASSIFIED MODELS: none")
        lines.append("")
    return "\n".join(lines)


def post_reset_counts() -> dict[str, int]:
    User = get_user_model()
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    return {
        "users": User.objects.count(),
        "superusers": User.objects.filter(is_superuser=True).count(),
        "employees": EmployeeProfile.objects.count(),
        "active_employees": EmployeeProfile.objects.filter(
            is_active_employee=True
        ).count(),
        "districts": _count(_get_model("masters.District")),
        "taluks": _count(_get_model("masters.Taluk")),
        "villages": _count(_get_model("masters.Village")),
        "assignments": _count(_get_model("accounts.EmployeeLocationAssignment")),
        "farmers": _count(_get_model("masters.Farmer")),
        "farmer_fields": _count(_get_model("masters.FarmerField")),
        "visits": _count(_get_model("visits.Visit")),
        "visit_media": _count(_get_model("visits.VisitMedia")),
        "crop_issues": _count(_get_model("masters.CropIssue")),
        "recommendations": _count(_get_model("masters.Recommendation")),
        "route_points": _count(_get_model("tracking.EmployeeRoutePoint")),
        "live_locations": _count(_get_model("tracking.EmployeeLiveLocation")),
        "duty_sessions": _count(_get_model("tracking.DutySession")),
        "workdays": _count(_get_model("tracking.WorkDay")),
        "crops": _count(_get_model("masters.Crop")),
        "problem_categories": _count(_get_model("masters.ProblemCategory")),
        "problem_items": _count(_get_model("masters.ProblemMaster")),
    }
