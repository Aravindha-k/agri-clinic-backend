#!/usr/bin/env bash
# Mandatory pre-deploy PostgreSQL backup for Kavya Agri Clinic backend.
# Runs ON EC2 from the Django project root BEFORE any migration.
#
# Exit codes:
#   0  backup created and verified
#   1  any failure (deployment MUST abort)
#   2  deliberate override acknowledged (SKIP_DB_BACKUP=YES + ALLOW_UNSAFE_DEPLOY=YES)
#
# Verification performed:
#   - pg_dump -Fc exit status
#   - output file exists and is plausibly non-trivial (>= 100 KB)
#   - pg_restore -l TOC parses and contains core Django tables
# Never prints DB passwords or connection strings with credentials.
set -Eeuo pipefail

log() { echo "[pre-deploy-backup] $(date -u +"%Y-%m-%dT%H:%M:%SZ") $*"; }
fail() { log "ERROR: $*"; exit 1; }

# --- Deliberate override: two flags required, always logged loudly ------------
if [ "${SKIP_DB_BACKUP:-}" = "YES" ]; then
  if [ "${ALLOW_UNSAFE_DEPLOY:-}" = "YES" ]; then
    log "WARNING: SKIP_DB_BACKUP=YES + ALLOW_UNSAFE_DEPLOY=YES — proceeding WITHOUT backup."
    log "This override is only acceptable for non-destructive hotfix redeploys."
    exit 2
  fi
  fail "SKIP_DB_BACKUP=YES requires ALLOW_UNSAFE_DEPLOY=YES as second confirmation."
fi

PYTHON="${PYTHON_BIN:-./.venv/bin/python}"
[ -f manage.py ] || fail "manage.py not found — run from Django project root"
[ -x "$PYTHON" ] || fail "Python not executable: $PYTHON"
command -v pg_dump >/dev/null 2>&1 || fail "pg_dump not found on PATH"
command -v pg_restore >/dev/null 2>&1 || fail "pg_restore not found on PATH"

BACKUP_DIR="backups/deploy"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +"%Y%m%d_%H%M%S")"
BACKUP_FILE="${BACKUP_DIR}/pre_deploy_${STAMP}.dump"
[ ! -e "$BACKUP_FILE" ] || fail "Backup path already exists: ${BACKUP_FILE}"
export BACKUP_FILE

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
    print(f"[pre-deploy-backup] ERROR: expected PostgreSQL, got {db.get('ENGINE')}", file=sys.stderr)
    raise SystemExit(1)

host = (db.get("HOST") or "").strip().lower()
if host.startswith("dpg-") or host.endswith(".render.com") or "render.com" in host:
    print("[pre-deploy-backup] ERROR: DB host resolves to Render — refusing to back up wrong database", file=sys.stderr)
    raise SystemExit(1)

outfile = Path(os.environ["BACKUP_FILE"])
env = os.environ.copy()
password = db.get("PASSWORD") or ""
if password:
    env["PGPASSWORD"] = password

cmd = [
    "pg_dump", "-Fc",
    "-h", str(db.get("HOST") or "127.0.0.1"),
    "-p", str(db.get("PORT") or "5432"),
    "-U", str(db.get("USER") or "postgres"),
    "-d", str(db.get("NAME") or "postgres"),
    "-f", str(outfile),
]
proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
if proc.returncode != 0:
    print(f"[pre-deploy-backup] ERROR: pg_dump exit={proc.returncode}", file=sys.stderr)
    err = (proc.stderr or proc.stdout or "").strip()
    if err:
        print(err[:500], file=sys.stderr)
    raise SystemExit(proc.returncode)
print(f"[pre-deploy-backup] pg_dump exit=0 host={db.get('HOST')} name={db.get('NAME')}")
PY

[ -f "$BACKUP_FILE" ] || fail "Backup file missing after pg_dump"
BACKUP_SIZE="$(stat -c%s "$BACKUP_FILE")"
log "Backup size: ${BACKUP_SIZE} bytes"
[ "${BACKUP_SIZE}" -ge 100000 ] || fail "Backup size ${BACKUP_SIZE} bytes is not plausibly non-trivial. STOP."

log "Verifying backup integrity (pg_restore -l + core table presence)"
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
proc = subprocess.run(["pg_restore", "-l", str(backup)], capture_output=True, text=True)
if proc.returncode != 0:
    print(f"[pre-deploy-backup] ERROR: pg_restore -l exit={proc.returncode}", file=sys.stderr)
    print((proc.stderr or "")[:500], file=sys.stderr)
    raise SystemExit(1)

toc = proc.stdout or ""
if toc.count("\n") < 20:
    print("[pre-deploy-backup] ERROR: TOC implausibly small", file=sys.stderr)
    raise SystemExit(1)

checks = {
    "User/auth": get_user_model()._meta.db_table,
    "EmployeeProfile": apps.get_model("accounts", "EmployeeProfile")._meta.db_table,
    "Village": apps.get_model("masters", "Village")._meta.db_table,
    "Farmer": apps.get_model("masters", "Farmer")._meta.db_table,
    "Visit": apps.get_model("visits", "Visit")._meta.db_table,
}
missing = []
for label, table in checks.items():
    ok = table in toc
    print(f"[pre-deploy-backup]   {label}: {table} => {'PASS' if ok else 'FAIL'}")
    if not ok:
        missing.append(f"{label}/{table}")
if missing:
    print("[pre-deploy-backup] ERROR missing core tables: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print(f"[pre-deploy-backup] BACKUP VERIFIED: {backup} ({backup.stat().st_size} bytes)")
print(f"BACKUP_FILE_PATH={backup}")
PY

log "SUCCESS — backup verified: ${BACKUP_FILE}"
log "REMINDER: copy this file off-server before proceeding (see docs/BACKUP_AND_RESTORE.md)"
