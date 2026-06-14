"""
Clean development/test transactional data before production use.

Keeps: admin/staff login accounts, location/crop/problem masters, system config.
Deletes: all visits, farmers, field employees (non-staff), and tracking/test data.

Usage:
  python manage.py clean_test_data --dry-run
  python manage.py clean_test_data --confirm
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Model, Q, QuerySet


# ---------------------------------------------------------------------------
# Table classification (audit)
# ---------------------------------------------------------------------------

KEEP_TABLES: dict[str, str] = {
    "auth_user": "Admin/staff accounts only (field employees removed)",
    "auth_group": "Django groups / roles",
    "auth_permission": "Django permissions",
    "django_content_type": "Django content types",
    "accounts_adminsecuritystate": "Admin lockout / security state",
    "masters_district": "Location master",
    "masters_village": "Location master",
    "masters_crop": "Crop master (KEEP)",
    "masters_problemcategory": "Problem category master",
    "masters_problemmaster": "Problem items / pest-disease master (KEEP)",
    "system_settings_systemconfig": "App GPS/tracking config singleton",
    "system_settings_systemsetting": "App settings key-value store",
    "django_migrations": "Migration history",
    "django_session": "Web sessions (see --clear-sessions)",
}

DELETE_TABLES: dict[str, str] = {
    "masters_recommendation": "Visit issue recommendations (transactional)",
    "masters_cropissue": "Crop issues raised from visits",
    "masters_farmeractivity": "Farmer activity timeline from visits/tests",
    "visits_visitmedia": "Visit uploaded media files",
    "visits_visitattachment": "Visit evidence attachments",
    "visits_visit": "Field visit records",
    "tracking_locationlog": "GPS route history",
    "tracking_availabilityevent": "Tracking availability events",
    "tracking_workday": "Employee workday sessions",
    "tracking_employeedailysummary": "Pre-computed tracking summaries",
    "tracking_worklog": "Legacy work log sessions",
    "reports_report": "Generated report jobs + files",
    "notifications_notification": "In-app notifications from testing",
    "audit_logs_auditlog": "Audit trail from dev/testing",
    "django_admin_log": "Django admin action log",
    "masters_fieldcrop": "Farmer field crop plantings (operational)",
    "masters_farmerfield": "Farmer land parcels (operational)",
    "masters_farmer": "Farmer registry (all)",
    "accounts_employeedevicesession": "Mobile device sessions (all)",
    "accounts_employeeprofile": "Field employee profiles (non-staff)",
    "auth_user_field_agents": "Field agent login accounts (non-staff users)",
}

UNSURE_TABLES: dict[str, str] = {
    "accounts_adminsession": "Admin panel sessions (--clear-sessions deletes)",
    "django_session": "Browser sessions (--clear-sessions deletes)",
}


def _field_employee_users_qs():
    """Field agents only — never staff/superuser admin accounts."""
    User = get_user_model()
    return User.objects.filter(employee_profile__isnull=False).exclude(
        Q(is_staff=True) | Q(is_superuser=True)
    )


def _is_production_env() -> bool:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if app_env in {"prod", "production", "render", "staging"}:
        return True
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


def _model_for_table(table: str) -> Model | None:
    for model in apps.get_models():
        if model._meta.db_table == table:
            return model
    return None


def _worklog_model() -> Model | None:
    try:
        from tracking.worklog import WorkLog

        return WorkLog
    except Exception:
        return None


def _delete_plan(*, clear_sessions: bool) -> list[tuple[str, Model, QuerySet]]:
    """FK-safe delete order (children before parents)."""
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

    from accounts.models import EmployeeDeviceSession, EmployeeProfile

    field_users = _field_employee_users_qs()
    plan.extend(
        [
            (
                "accounts_employeedevicesession",
                EmployeeDeviceSession,
                EmployeeDeviceSession.objects.all(),
            ),
            (
                "accounts_employeeprofile",
                EmployeeProfile,
                EmployeeProfile.objects.filter(user__in=field_users),
            ),
            (
                "auth_user_field_agents",
                get_user_model(),
                field_users,
            ),
        ]
    )

    worklog = _worklog_model()
    if worklog is not None:
        plan.insert(
            10,
            ("tracking_worklog", worklog, worklog.objects.all()),
        )

    if clear_sessions:
        from accounts.models import AdminSession
        from django.contrib.sessions.models import Session

        plan.extend(
            [
                ("accounts_adminsession", AdminSession, AdminSession.objects.all()),
                ("django_session", Session, Session.objects.all()),
            ]
        )

    return plan


def _count_rows(model: Model, qs: QuerySet) -> int:
    try:
        return qs.count()
    except Exception:
        return -1


def _collect_media_paths(plan: list[tuple[str, Model, QuerySet]]) -> list[Path]:
    paths: list[Path] = []

    for _table, model, qs in plan:
        if model._meta.db_table == "visits_visitmedia":
            for row in qs.only("file"):
                if row.file:
                    paths.append(Path(row.file.path))
        elif model._meta.db_table == "visits_visitattachment":
            for row in qs.only("file"):
                if row.file:
                    paths.append(Path(row.file.path))
        elif model._meta.db_table == "reports_report":
            for row in qs.only("file"):
                if row.file:
                    paths.append(Path(row.file.path))
        elif model._meta.db_table == "masters_farmer":
            for row in qs.only("profile_photo"):
                if row.profile_photo:
                    paths.append(Path(row.profile_photo.path))
        elif model._meta.db_table == "accounts_employeeprofile":
            for row in qs.only("profile_photo"):
                if row.profile_photo:
                    paths.append(Path(row.profile_photo.path))

    existing = [p for p in paths if p.exists()]
    return existing


def _create_db_backup(backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    engine = connection.settings_dict.get("ENGINE", "")

    db = connection.settings_dict
    if "postgresql" in engine:
        outfile = backup_dir / f"agri_clinic_pre_clean_{stamp}.sql"
        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = str(db["PASSWORD"])
        cmd = [
            "pg_dump",
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
        except FileNotFoundError as exc:
            raise CommandError(
                "pg_dump not found. Install PostgreSQL client tools or create a manual backup."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"pg_dump failed: {exc.stderr}") from exc
        return outfile

    if "sqlite" in engine:
        src = Path(db["NAME"])
        outfile = backup_dir / f"agri_clinic_pre_clean_{stamp}.sqlite3"
        shutil.copy2(src, outfile)
        return outfile

    raise CommandError(f"Unsupported database engine for auto-backup: {engine}")


class Command(BaseCommand):
    help = (
        "Fresh production reset: removes visits, farmers, field employees, tracking, "
        "and test logs. Keeps admin/staff logins and master data (crops, problem masters)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show tables and row counts that would be deleted (default).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Apply deletions after creating a DB backup.",
        )
        parser.add_argument(
            "--backup-dir",
            default="",
            help="Directory for DB backup (default: <project>/backups/).",
        )
        parser.add_argument(
            "--skip-backup",
            action="store_true",
            help="Skip automatic backup (not recommended).",
        )
        parser.add_argument(
            "--clear-sessions",
            action="store_true",
            help="Also clear mobile/admin/web sessions (users must re-login).",
        )
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="Allow running when APP_ENV indicates production.",
        )

    def handle(self, *args, **options):
        if options["confirm"] and options["dry_run"]:
            raise CommandError("Use either --dry-run or --confirm, not both.")

        dry_run = not options["confirm"]
        if not options["confirm"] and not options["dry_run"]:
            dry_run = True

        if _is_production_env() and not options["allow_production"]:
            raise CommandError(
                "Production-like environment detected. Pass --allow-production "
                "only after reviewing the audit output."
            )

        self._print_audit_report(clear_sessions=options["clear_sessions"])

        plan = _delete_plan(clear_sessions=options["clear_sessions"])
        counts = [
            (table, model._meta.label, _count_rows(model, qs))
            for table, model, qs in plan
        ]
        media_files = _collect_media_paths(plan)
        total_rows = sum(c for _, _, c in counts if c > 0)

        self.stdout.write(self.style.MIGRATE_HEADING("\nDELETE plan (FK-safe order)"))
        for table, label, count in counts:
            style = self.style.WARNING if count else self.style.NOTICE
            self.stdout.write(style(f"  {table:35} {label:30} {count:>8} rows"))
        self.stdout.write(f"\n  Media files to remove: {len(media_files)}")
        self.stdout.write(f"  Total rows to delete:  {total_rows}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry-run only — no data deleted. "
                    "Re-run with --confirm after reviewing the audit above."
                )
            )
            return

        if total_rows == 0 and not media_files and not options["clear_sessions"]:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        backup_path = None
        if not options["skip_backup"]:
            backup_dir = Path(options["backup_dir"] or (settings.BASE_DIR / "backups"))
            self.stdout.write(f"\nCreating database backup in {backup_dir} ...")
            backup_path = _create_db_backup(backup_dir)
            self.stdout.write(self.style.SUCCESS(f"Backup saved: {backup_path}"))

        deleted_summary: dict[str, int] = {}
        with transaction.atomic():
            for table, model, qs in plan:
                count = _count_rows(model, qs)
                if count <= 0:
                    deleted_summary[table] = 0
                    continue
                deleted, _detail = qs.delete()
                deleted_summary[table] = deleted
                self.stdout.write(f"  Deleted {table}: {deleted}")

            for path in media_files:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    raise CommandError(f"Failed to delete media file {path}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("\n=== Cleanup complete ==="))
        if backup_path:
            self.stdout.write(f"  Backup: {backup_path}")
        self.stdout.write(f"  Rows deleted: {sum(deleted_summary.values())}")
        self.stdout.write(f"  Media files removed: {len(media_files)}")
        User = get_user_model()
        admins_left = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"  Preserved: {admins_left} admin/staff account(s), crops, problem masters, "
                "categories, districts, villages, system config."
            )
        )

        try:
            from dashboard.services import invalidate_dashboard_caches

            invalidate_dashboard_caches()
        except Exception:
            pass

    def _print_audit_report(self, *, clear_sessions: bool) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("=== A. KEEP (master + auth) ==="))
        User = get_user_model()
        for table, reason in sorted(KEEP_TABLES.items()):
            if table == "auth_user":
                count = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).count()
            else:
                model = _model_for_table(table)
                count = model.objects.count() if model else "n/a"
            self.stdout.write(f"  {table:35} {count!s:>8}  {reason}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== B. DELETE (transaction / test) ==="))
        for table, reason in sorted(DELETE_TABLES.items()):
            if table == "tracking_worklog":
                model = _worklog_model()
                count = model.objects.count() if model else "n/a"
            elif table == "auth_user_field_agents":
                count = _field_employee_users_qs().count()
            elif table == "accounts_employeeprofile":
                from accounts.models import EmployeeProfile

                count = EmployeeProfile.objects.filter(
                    user__in=_field_employee_users_qs()
                ).count()
            else:
                model = _model_for_table(table)
                count = model.objects.count() if model else "n/a"
            self.stdout.write(f"  {table:35} {count!s:>8}  {reason}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== C. UNSURE (optional flags) ==="))
        for table, reason in sorted(UNSURE_TABLES.items()):
            model = _model_for_table(table)
            count = model.objects.count() if model else "n/a"
            flag = (
                "WILL DELETE (--clear-sessions)"
                if clear_sessions
                else "KEEP (default)"
            )
            self.stdout.write(f"  {table:35} {count!s:>8}  {reason} [{flag}]")
