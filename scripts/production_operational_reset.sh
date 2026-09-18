#!/usr/bin/env bash
# Production operational reset with mandatory backup gates.
# Run ON EC2 from the Django project root via the ops workflow.
#
# Required env:
#   EXPECTED_SHA
#   CONFIRM_EXECUTE          (= RESET KAVYA OPERATIONAL DATA)
#   ALLOW_PRODUCTION_RESET   (= YES)
#
# Never prints DB passwords, AWS secrets, or password hashes.
set -Eeuo pipefail

EXPECTED_SHA="${EXPECTED_SHA:?EXPECTED_SHA required}"
CONFIRM_EXECUTE="${CONFIRM_EXECUTE:?CONFIRM_EXECUTE required}"
ALLOW_PRODUCTION_RESET="${ALLOW_PRODUCTION_RESET:?ALLOW_PRODUCTION_RESET required}"
REQUIRED_PHRASE="RESET KAVYA OPERATIONAL DATA"
PYTHON="${PYTHON_BIN:-./.venv/bin/python}"

log() { echo "[ops-reset] $(date -u +"%Y-%m-%dT%H:%M:%SZ") $*"; }
fail() { log "ERROR: $*"; exit 1; }

[ -f manage.py ] || fail "manage.py not found"
[ -x "$PYTHON" ] || fail "Python not executable: $PYTHON"
[ -f .env ] || fail ".env missing"

HEAD="$(git rev-parse HEAD)"
log "PRODUCTION SHA: ${HEAD}"
[ "$HEAD" = "$EXPECTED_SHA" ] || fail "Production HEAD ${HEAD} != expected ${EXPECTED_SHA}. STOP."

[ -f system_settings/management/commands/reset_operational_data.py ] \
  || fail "reset_operational_data missing"
[ -f system_settings/operational_reset.py ] \
  || fail "operational_reset missing"

if grep -E "manage\.py import_business_locations|manage\.py resolve_backfill_review" \
  .github/workflows/backend-deploy.yml scripts/deploy_production.sh >/dev/null 2>&1; then
  fail "Automatic location import/backfill still in deploy paths. STOP."
fi
log "Reviewed reset implementation present; auto location imports absent from deploy."

[ "$ALLOW_PRODUCTION_RESET" = "YES" ] || fail "ALLOW_PRODUCTION_RESET must be YES"
[ "$CONFIRM_EXECUTE" = "$REQUIRED_PHRASE" ] || fail "CONFIRM_EXECUTE phrase mismatch"

mkdir -p backups/manual
STAMP="$(date -u +"%Y%m%d_%H%M%S")"
BACKUP_FILE="backups/manual/pre_operational_reset_${STAMP}.dump"
[ ! -e "$BACKUP_FILE" ] || fail "Backup path already exists: ${BACKUP_FILE}"
export BACKUP_FILE
BACKUP_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export BACKUP_STARTED_AT

log "Creating PostgreSQL custom-format backup: ${BACKUP_FILE}"
"$PYTHON" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings

db = settings.DATABASES["default"]
if "postgresql" not in (db.get("ENGINE") or ""):
    print(f"[ops-reset] ERROR: expected PostgreSQL, got {db.get('ENGINE')}", file=sys.stderr)
    raise SystemExit(1)

outfile = Path(os.environ["BACKUP_FILE"])
if outfile.exists():
    print(f"[ops-reset] ERROR: refusing to overwrite {outfile}", file=sys.stderr)
    raise SystemExit(1)

env = os.environ.copy()
password = db.get("PASSWORD") or ""
if password:
    env["PGPASSWORD"] = password

cmd = [
    "pg_dump",
    "-Fc",
    "-h",
    str(db.get("HOST") or "127.0.0.1"),
    "-p",
    str(db.get("PORT") or "5432"),
    "-U",
    str(db.get("USER") or "postgres"),
    "-d",
    str(db.get("NAME") or "postgres"),
    "-f",
    str(outfile),
]
proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
if proc.returncode != 0:
    print(f"[ops-reset] ERROR: pg_dump failed exit={proc.returncode}", file=sys.stderr)
    err = (proc.stderr or proc.stdout or "").strip()
    if err:
        print(err[:500], file=sys.stderr)
    raise SystemExit(proc.returncode)
print("[ops-reset] pg_dump exit=0")
PY

[ -f "$BACKUP_FILE" ] || fail "Backup file missing after pg_dump"
BACKUP_SIZE="$(stat -c%s "$BACKUP_FILE")"
log "BACKUP SIZE bytes: ${BACKUP_SIZE}"
[ "${BACKUP_SIZE}" -ge 100000 ] || fail "Backup size ${BACKUP_SIZE} not plausibly non-trivial. STOP."

log "Verifying pg_restore -l + Django table names"
"$PYTHON" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.apps import apps
from django.contrib.auth import get_user_model

backup = Path(os.environ["BACKUP_FILE"])
proc = subprocess.run(
    ["pg_restore", "-l", str(backup)],
    capture_output=True,
    text=True,
)
if proc.returncode != 0:
    print(f"[ops-reset] ERROR: pg_restore -l failed exit={proc.returncode}", file=sys.stderr)
    print((proc.stderr or "")[:500], file=sys.stderr)
    raise SystemExit(1)
toc = proc.stdout or ""
if toc.count("\n") < 20:
    print("[ops-reset] ERROR: pg_restore -l output too small", file=sys.stderr)
    raise SystemExit(1)

checks = {
    "User/auth": get_user_model()._meta.db_table,
    "EmployeeProfile": apps.get_model("accounts", "EmployeeProfile")._meta.db_table,
    "Village": apps.get_model("masters", "Village")._meta.db_table,
    "Farmer": apps.get_model("masters", "Farmer")._meta.db_table,
    "Visit": apps.get_model("visits", "Visit")._meta.db_table,
}
print("[ops-reset] PG_RESTORE LIST: PASS")
print("[ops-reset] ACTUAL TABLES VERIFIED:")
missing = []
for label, table in checks.items():
    ok = table in toc
    print(f"  {label}: {table} => {'PASS' if ok else 'FAIL'}")
    if not ok:
        missing.append(f"{label}/{table}")
if missing:
    print("[ops-reset] ERROR missing tables: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print(f"[ops-reset] BACKUP STARTED AT: {os.environ.get('BACKUP_STARTED_AT')} (before reset)")
print("[ops-reset] BACKUP: PASS")
print(f"[ops-reset] BACKUP FILE: {backup}")
print(f"[ops-reset] BACKUP SIZE: {backup.stat().st_size}")
PY

log "Copying backup off-server to S3 (required gate)"
"$PYTHON" <<'PY'
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings

backup = Path(os.environ["BACKUP_FILE"])
bucket = (
    (os.getenv("AWS_STORAGE_BUCKET_NAME") or "")
    or (getattr(settings, "AWS_STORAGE_BUCKET_NAME", None) or "")
).strip()
prefix = (os.getenv("S3_BACKUP_URI_PREFIX") or "").strip()
region = (
    (os.getenv("AWS_S3_REGION_NAME") or "")
    or (getattr(settings, "AWS_S3_REGION_NAME", None) or "ap-south-1")
)
ak = (os.getenv("AWS_ACCESS_KEY_ID") or getattr(settings, "AWS_ACCESS_KEY_ID", None) or "").strip()
sk = (
    os.getenv("AWS_SECRET_ACCESS_KEY") or getattr(settings, "AWS_SECRET_ACCESS_KEY", None) or ""
).strip()

if prefix:
    uri = prefix.rstrip("/") + "/" + backup.name
else:
    if not bucket:
        print(
            "[ops-reset] ERROR: No established off-server destination "
            "(AWS_STORAGE_BUCKET_NAME / S3_BACKUP_URI_PREFIX unset on server). STOP before reset.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    uri = f"s3://{bucket}/agri-clinic/db-backups/{backup.name}"

parsed = urlparse(uri)
if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
    print(f"[ops-reset] ERROR: invalid S3 URI shape", file=sys.stderr)
    raise SystemExit(2)

try:
    import boto3
except ImportError:
    print("[ops-reset] ERROR: boto3 not installed on server", file=sys.stderr)
    raise SystemExit(3)

kwargs = {"region_name": str(region)}
if ak and sk:
    kwargs["aws_access_key_id"] = ak
    kwargs["aws_secret_access_key"] = sk

client = boto3.client("s3", **kwargs)
bkt = parsed.netloc
key = parsed.path.lstrip("/")
try:
    client.upload_file(str(backup), bkt, key)
    head = client.head_object(Bucket=bkt, Key=key)
except Exception as exc:
    print(
        f"[ops-reset] ERROR: off-server S3 copy failed ({type(exc).__name__}). STOP before reset.",
        file=sys.stderr,
    )
    raise SystemExit(3)

size = int(head.get("ContentLength") or 0)
if size < 100000:
    print(
        f"[ops-reset] ERROR: off-server object size {size} not plausible. STOP.",
        file=sys.stderr,
    )
    raise SystemExit(3)

# URI only — never credentials.
print(f"[ops-reset] OFF-SERVER BACKUP URI: {uri}")
print(f"[ops-reset] OFF-SERVER BACKUP SIZE: {size}")
print("[ops-reset] OFF-SERVER BACKUP: PASS")
PY

log "Capturing pre-reset critical counts"
"$PYTHON" <<'PY'
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from system_settings.operational_reset import collect_plan, critical_counts

counts = critical_counts()
print("--- PRE-RESET COUNTS ---")
for k, v in counts.items():
    print(f"{k}: {v}")

expected = {
    "EmployeeProfiles": 11,
    "Farmer": 1856,
    "Village": 1462,
    "Visit": 9,
}
drift = {k: counts[k] for k in expected if counts.get(k) != expected[k]}
if drift:
    print("[ops-reset] ERROR: counts drifted from reviewed dry-run:", drift, file=sys.stderr)
    raise SystemExit(1)

plan = collect_plan()
print("--- PRE-RESET PRESERVE SNAPSHOT ---")
for k in (
    "Users",
    "Superusers",
    "Admins (is_staff)",
    "EmployeeProfiles",
    "Active Employees",
    "Crops",
    "Problem Categories",
    "Problem Items",
    "Crop↔problem mappings",
):
    print(f"{k}: {plan.preserve.get(k)}")
print("PRE-RESET COUNTS: PASS")
PY

log "Executing approved reset"
set +e
"$PYTHON" manage.py reset_operational_data \
  --execute \
  --confirm-phrase="${REQUIRED_PHRASE}" \
  --allow-production
RESET_RC=$?
set -e
if [ "$RESET_RC" -ne 0 ]; then
  log "RESET COMMAND: FAIL"
  log "TRANSACTION: ROLLED BACK"
  fail "reset_operational_data failed with exit ${RESET_RC}"
fi
log "RESET COMMAND: PASS"
log "TRANSACTION: COMMITTED"

log "Post-reset verification"
"$PYTHON" <<'PY'
import sys

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Q
from system_settings.operational_reset import _count, _get_model, _m2m_through_count, _worklog_model

User = get_user_model()
EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")

preserve = {
    "Users": User.objects.count(),
    "Superusers": User.objects.filter(is_superuser=True).count(),
    "Admins": User.objects.filter(is_staff=True).count(),
    "EmployeeProfiles": EmployeeProfile.objects.count(),
    "Active Employees": EmployeeProfile.objects.filter(is_active_employee=True).count(),
    "Crops": _count(_get_model("masters.Crop")),
    "Problem Categories": _count(_get_model("masters.ProblemCategory")),
    "Problem Items": _count(_get_model("masters.ProblemMaster")),
    "Crop/problem mappings": _count(_get_model("masters.CropProblem")),
    "Audit logs": _count(_get_model("audit_logs.AuditLog")),
    "Admin sessions": _count(_get_model("accounts.AdminSession")),
    "Admin security states": _count(_get_model("accounts.AdminSecurityState")),
    "Employee device sessions": _count(_get_model("accounts.EmployeeDeviceSession")),
    "Django sessions": _count(_get_model("sessions.Session")),
    "JWT outstanding": _count(_get_model("token_blacklist.OutstandingToken")),
    "JWT blacklisted": _count(_get_model("token_blacklist.BlacklistedToken")),
}
print("--- PRESERVED AFTER RESET ---")
for k, v in preserve.items():
    print(f"{k}: {v}")

expected_preserve = {
    "Users": 15,
    "Superusers": 3,
    "Admins": 4,
    "EmployeeProfiles": 11,
    "Active Employees": 11,
    "Crops": 51,
    "Problem Categories": 9,
    "Problem Items": 145,
    "Crop/problem mappings": 140,
}
bad = {k: preserve[k] for k in expected_preserve if preserve[k] != expected_preserve[k]}
if bad:
    print("[ops-reset] ERROR preserve mismatch:", bad, file=sys.stderr)
    raise SystemExit(1)

profiles = list(EmployeeProfile.objects.select_related("user").all())
missing_ids = [p.pk for p in profiles if not (p.employee_id or "").strip()]
missing_users = [p.pk for p in profiles if p.user_id is None]
empty_passwords = [p.user_id for p in profiles if not (p.user.password or "").strip()]
photos = (
    EmployeeProfile.objects.exclude(profile_photo="")
    .exclude(profile_photo__isnull=True)
    .count()
)
legacy_loc = EmployeeProfile.objects.filter(
    Q(district_id__isnull=False) | Q(village_id__isnull=False)
).count()
print(f"employee_ids_present: {len(profiles) - len(missing_ids)}/{len(profiles)}")
print(f"employee_user_links_present: {len(profiles) - len(missing_users)}/{len(profiles)}")
print(f"password_hashes_populated: {len(profiles) - len(empty_passwords)}/{len(profiles)}")
print(f"employee_photos_with_file: {photos}")
print(f"employee_legacy_location_refs_remaining: {legacy_loc}")
if missing_ids or missing_users or empty_passwords:
    raise SystemExit("employee/auth preservation check failed")
print(
    "EMPLOYEE LEGACY LOCATION REFERENCES CLEARED:",
    "YES" if legacy_loc == 0 else "NO",
)
print("EMPLOYEE PHOTOS PRESERVED:", "YES" if photos >= 1 else "CHECK")
print("PASSWORD/AUTH PRESERVED: YES")

operational = {
    "District": _count(_get_model("masters.District")),
    "Taluk": _count(_get_model("masters.Taluk")),
    "Village": _count(_get_model("masters.Village")),
    "EmployeeLocationAssignment": _count(
        _get_model("accounts.EmployeeLocationAssignment")
    ),
    "Farmer": _count(_get_model("masters.Farmer")),
    "FarmerField": _count(_get_model("masters.FarmerField")),
    "FieldCrop": _count(_get_model("masters.FieldCrop")),
    "FarmerActivity": _count(_get_model("masters.FarmerActivity")),
    "Visit": _count(_get_model("visits.Visit")),
    "VisitMedia": _count(_get_model("visits.VisitMedia")),
    "VisitAttachment": _count(_get_model("visits.VisitAttachment")),
    "CropIssue": _count(_get_model("masters.CropIssue")),
    "Recommendation": _count(_get_model("masters.Recommendation")),
    "Visit problem links": _m2m_through_count("visits.Visit", "problem_items"),
    "DutySession": _count(_get_model("tracking.DutySession")),
    "WorkDay": _count(_get_model("tracking.WorkDay")),
    "WorkLog": _count(_worklog_model()),
    "EmployeeLiveLocation": _count(_get_model("tracking.EmployeeLiveLocation")),
    "EmployeeGpsState": _count(_get_model("tracking.EmployeeGpsState")),
    "EmployeeRoutePoint": _count(_get_model("tracking.EmployeeRoutePoint")),
    "LocationLog": _count(_get_model("tracking.LocationLog")),
    "AvailabilityEvent": _count(_get_model("tracking.AvailabilityEvent")),
    "EmployeeDailySummary": _count(_get_model("tracking.EmployeeDailySummary")),
    "Notification": _count(_get_model("notifications.Notification")),
    "Report": _count(_get_model("reports.Report")),
}
print("--- OPERATIONAL AFTER RESET ---")
nonzero = []
for k, v in operational.items():
    print(f"{k}: {v}")
    if v != 0:
        nonzero.append(f"{k}={v}")
if nonzero:
    print("[ops-reset] ERROR nonzero operational:", nonzero, file=sys.stderr)
    raise SystemExit(1)
print("OTHER OPERATIONAL MODELS: all audited models are zero")
PY

log "Django check + healthz"
"$PYTHON" manage.py check
curl -fsS --retry 5 --retry-delay 2 --retry-connrefused http://127.0.0.1:8000/healthz/
echo
log "DJANGO CHECK: PASS"
log "HEALTH: PASS"
log "ADMIN LOGIN: NOT TESTED"
log "EMPLOYEE LOGIN: NOT TESTED"
log "PHYSICAL MEDIA DELETED: NO"
log "EXCEL IMPORTED: NO"
log "MOBILE DEPLOYED: NO"
log "STOP."
