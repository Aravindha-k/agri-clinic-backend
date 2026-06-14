"""Farmer-related transactional data cleanup (keeps employees and masters)."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import Model, QuerySet

KEEP_TABLES: dict[str, str] = {
    "auth_user": "All login accounts (admin + field employees)",
    "auth_group": "Django groups / roles",
    "auth_permission": "Django permissions",
    "django_content_type": "Django content types",
    "accounts_adminsecuritystate": "Admin lockout / security state",
    "accounts_adminsession": "Admin panel sessions",
    "accounts_employeeprofile": "Field employee profiles",
    "accounts_employeedevicesession": "Mobile device sessions",
    "masters_district": "Location master",
    "masters_village": "Location master",
    "masters_crop": "Crop master",
    "masters_problemcategory": "Problem category master",
    "masters_problemmaster": "Problem items master",
    "system_settings_systemconfig": "App GPS/tracking config",
    "system_settings_systemsetting": "App settings",
    "django_migrations": "Migration history",
    "django_session": "Browser sessions",
}

DELETE_TABLES: dict[str, str] = {
    "masters_recommendation": "Recommendations linked to crop issues",
    "masters_cropissue": "Crop issues from visits",
    "masters_farmeractivity": "Farmer activity timeline",
    "visits_visitmedia": "Visit media uploads",
    "visits_visitattachment": "Visit evidence attachments",
    "visits_visit": "Field visit records",
    "tracking_locationlog": "GPS route history",
    "tracking_availabilityevent": "Tracking availability events",
    "tracking_workday": "Employee workday sessions",
    "tracking_employeedailysummary": "Tracking daily summaries",
    "tracking_worklog": "Legacy work log sessions",
    "reports_report": "Generated reports linked to old data",
    "notifications_notification": "In-app notifications from testing",
    "audit_logs_auditlog": "Audit trail from dev/testing",
    "django_admin_log": "Django admin action log",
    "masters_fieldcrop": "Farmer field crop plantings",
    "masters_farmerfield": "Farmer land parcels",
    "masters_farmer": "Farmer registry",
}

UNSURE_TABLES: dict[str, str] = {}


def _worklog_model() -> Model | None:
    try:
        from tracking.worklog import WorkLog

        return WorkLog
    except Exception:
        return None


def farmer_delete_plan() -> list[tuple[str, Model, QuerySet]]:
    """FK-safe delete order (children before parents). Does not touch users."""
    from audit_logs.models import AuditLog
    from masters.models import (
        CropIssue,
        Farmer,
        FarmerActivity,
        FarmerField,
        FieldCrop,
        Recommendation,
    )
    from notifications.models import Notification
    from reports.models import Report
    from tracking.models import (
        AvailabilityEvent,
        EmployeeDailySummary,
        LocationLog,
        WorkDay,
    )
    from visits.models import Visit, VisitAttachment, VisitMedia

    plan: list[tuple[str, Model, QuerySet]] = [
        ("masters_recommendation", Recommendation, Recommendation.objects.all()),
        ("masters_cropissue", CropIssue, CropIssue.objects.all()),
        ("masters_farmeractivity", FarmerActivity, FarmerActivity.objects.all()),
        ("visits_visitmedia", VisitMedia, VisitMedia.objects.all()),
        ("visits_visitattachment", VisitAttachment, VisitAttachment.objects.all()),
        ("visits_visit", Visit, Visit.objects.all()),
        ("tracking_locationlog", LocationLog, LocationLog.objects.all()),
        ("tracking_availabilityevent", AvailabilityEvent, AvailabilityEvent.objects.all()),
        ("tracking_workday", WorkDay, WorkDay.objects.all()),
        (
            "tracking_employeedailysummary",
            EmployeeDailySummary,
            EmployeeDailySummary.objects.all(),
        ),
        ("reports_report", Report, Report.objects.all()),
        ("notifications_notification", Notification, Notification.objects.all()),
        ("audit_logs_auditlog", AuditLog, AuditLog.objects.all()),
        ("django_admin_log", LogEntry, LogEntry.objects.all()),
        ("masters_fieldcrop", FieldCrop, FieldCrop.objects.all()),
        ("masters_farmerfield", FarmerField, FarmerField.objects.all()),
        ("masters_farmer", Farmer, Farmer.objects.all()),
    ]

    worklog = _worklog_model()
    if worklog is not None:
        plan.insert(
            7,
            ("tracking_worklog", worklog, worklog.objects.all()),
        )

    return plan


def _model_for_table(table: str) -> Model | None:
    for model in apps.get_models():
        if model._meta.db_table == table:
            return model
    return None


def count_delete_plan(plan: list[tuple[str, Model, QuerySet]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, _model, qs in plan:
        try:
            counts[table] = qs.count()
        except Exception:
            counts[table] = -1
    return counts


def audit_table_classification() -> dict[str, list[dict]]:
    """Classify every DB table as KEEP / DELETE / UNSURE with row counts."""
    all_tables = sorted(
        {model._meta.db_table for model in apps.get_models()}
        | set(KEEP_TABLES)
        | set(DELETE_TABLES)
        | set(UNSURE_TABLES)
    )

    def _bucket(table: str) -> str:
        if table in DELETE_TABLES:
            return "DELETE"
        if table in KEEP_TABLES:
            return "KEEP"
        if table in UNSURE_TABLES:
            return "UNSURE"
        return "UNSURE"

    sections: dict[str, list[dict]] = {"KEEP": [], "DELETE": [], "UNSURE": []}
    for table in all_tables:
        bucket = _bucket(table)
        model = _model_for_table(table)
        count = -1
        if model is not None:
            try:
                count = model.objects.count()
            except Exception:
                count = -1
        note = (
            DELETE_TABLES.get(table)
            or KEEP_TABLES.get(table)
            or UNSURE_TABLES.get(table)
            or "Not classified — review manually"
        )
        sections[bucket].append({"table": table, "count": count, "note": note})

    for bucket in sections:
        sections[bucket].sort(key=lambda row: row["table"])
    return sections


def _resolve_pg_dump() -> str:
    """Locate pg_dump on PATH or common Windows PostgreSQL install dirs."""
    import shutil

    found = shutil.which("pg_dump")
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"),
        Path(r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe"),
        Path(r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"),
        Path(r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"),
        Path(r"C:\Program Files\PostgreSQL\14\bin\pg_dump.exe"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    raise CommandError(
        "pg_dump not found. Install PostgreSQL client tools or create a manual backup."
    )


def create_db_backup(backup_dir: Path | None = None) -> Path:
    backup_dir = backup_dir or Path(settings.BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    engine = connection.settings_dict.get("ENGINE", "")
    db = connection.settings_dict

    if "postgresql" in engine:
        outfile = backup_dir / f"agri_clinic_pre_farmer_import_{stamp}.sql"
        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = str(db["PASSWORD"])
        cmd = [
            _resolve_pg_dump(),
            "-h",
            str(db.get("HOST") or "localhost"),
            "-p",
            str(db.get("PORT") or "5432"),
            "-U",
            str(db.get("USER") or "postgres"),
            "-d",
            str(db.get("NAME")),
            "-f",
            str(outfile),
            "--no-owner",
            "--no-acl",
        ]
        try:
            subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"pg_dump failed: {exc.stderr}") from exc
        return outfile

    if "sqlite" in engine:
        src = Path(db["NAME"])
        outfile = backup_dir / f"agri_clinic_pre_farmer_import_{stamp}.sqlite3"
        shutil.copy2(src, outfile)
        return outfile

    raise CommandError(f"Unsupported database engine for auto-backup: {engine}")


def execute_farmer_cleanup(plan: list[tuple[str, Model, QuerySet]]) -> dict[str, int]:
    deleted_counts: dict[str, int] = {}
    for table, model, qs in plan:
        count, _detail = qs.delete()
        deleted_counts[table] = count
    return deleted_counts
