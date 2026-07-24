#!/usr/bin/env bash
# Safe production deploy for Kavya Agri Clinic Django backend (EC2 Git checkout).
#
# Required environment variables:
#   DEPLOY_COMMIT      - exact Git commit SHA to deploy
#   DEPLOY_PATH        - repository root on server (default below)
#   SERVICE_NAME       - systemd unit to restart (e.g. agri-backend.service)
#
# Optional:
#   DEPLOY_BRANCH      - branch to fast-forward (default: main)
#   BACKEND_HEALTH_URL - health probe URL (default: http://127.0.0.1:8000/healthz/)
#   PYTHON_BIN         - override python binary path
#   RUN_DB_BACKUP      - true|false (default: true) pre-migration pg_dump when Postgres
#
# Never prints .env contents, DATABASE_URL, SECRET_KEY, or SSH material.
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/var/www/agri-backend/agri-clinic-backend}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://127.0.0.1:8000/healthz/}"
RUN_DB_BACKUP="${RUN_DB_BACKUP:-true}"

log() { echo "[deploy] $(date -u +"%Y-%m-%dT%H:%M:%SZ") $*"; }
fail() { log "ERROR: $*"; exit 1; }

on_err() {
  log "Deployment failed at line ${1:-unknown}"
  exit 1
}
trap 'on_err $LINENO' ERR

require_var() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    fail "Missing required environment variable: $name"
  fi
}

require_var DEPLOY_COMMIT
require_var SERVICE_NAME

log "Starting deployment"
log "Target commit: ${DEPLOY_COMMIT}"
log "Deploy path: ${DEPLOY_PATH}"
log "Service: ${SERVICE_NAME}"
log "Branch: ${DEPLOY_BRANCH}"

[ -d "$DEPLOY_PATH" ] || fail "Deploy path does not exist: $DEPLOY_PATH"
cd "$DEPLOY_PATH"

[ -d .git ] || fail "Not a Git repository: $DEPLOY_PATH"
[ -f .env ] || fail ".env not found — refusing to deploy without production environment"
[ -x .venv/bin/python ] || fail ".venv/bin/python not found or not executable"

PREVIOUS_COMMIT="$(git rev-parse HEAD)"
log "Previous commit: ${PREVIOUS_COMMIT}"

# Allow known server-local/generated paths; block unexpected modifications.
check_worktree() {
  local line path status_xy
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    status_xy="${line:0:2}"
    path="${line:3}"

    case "$path" in
      .env|.env.*|media/*|staticfiles/*|backups/*|db.sqlite3|*.log|*.pyc|*.sql|*.dump)
        continue
        ;;
    esac
    case "$path" in
      *__pycache__/*|*/__pycache__/*)
        continue
        ;;
    esac

    # Tracked modifications outside allow-list are blocking.
    if [[ "$status_xy" =~ [MADRCU] ]]; then
      fail "Unexpected tracked change: $path (status: $status_xy). Resolve on server before deploy."
    fi

    # Unexpected untracked files (not in allow-list).
    if [[ "$status_xy" == "??" ]]; then
      fail "Unexpected untracked path: $path. Move or commit intentionally before deploy."
    fi
  done < <(git status --porcelain --untracked-files=all)
}

log "Checking working tree cleanliness"
check_worktree

log "Fetching origin/${DEPLOY_BRANCH}"
git fetch origin "$DEPLOY_BRANCH"

git cat-file -e "${DEPLOY_COMMIT}^{commit}" \
  || fail "Commit ${DEPLOY_COMMIT} not found after fetch"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
  fail "Detached HEAD state — checkout ${DEPLOY_BRANCH} before deploying"
fi

if [ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]; then
  log "Checking out ${DEPLOY_BRANCH}"
  git checkout "$DEPLOY_BRANCH"
fi

log "Fast-forwarding ${DEPLOY_BRANCH} to ${DEPLOY_COMMIT}"
git merge --ff-only "$DEPLOY_COMMIT" \
  || fail "Cannot fast-forward to ${DEPLOY_COMMIT}. Manual intervention required."

DEPLOYED_COMMIT="$(git rev-parse HEAD)"
log "Active tree commit: ${DEPLOYED_COMMIT}"

PYTHON="${PYTHON_BIN:-./.venv/bin/python}"
log "Using Python: ${PYTHON}"

log "Upgrading pip and installing requirements"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r requirements.txt

optional_db_backup() {
  if [ "$RUN_DB_BACKUP" != "true" ]; then
    log "Skipping database backup (RUN_DB_BACKUP=${RUN_DB_BACKUP})"
    return 0
  fi
  log "Creating optional pre-migration database backup"
  "$PYTHON" <<'PY' || log "WARNING: backup step failed — continuing (set RUN_DB_BACKUP=false to skip)"
import datetime
import os
import subprocess
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings

db = settings.DATABASES["default"]
engine = db.get("ENGINE", "")
if "postgresql" not in engine:
    print("[deploy] skip backup: non-PostgreSQL engine")
    raise SystemExit(0)

backup_dir = Path(settings.BASE_DIR) / "backups" / "deploy"
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
outfile = backup_dir / f"pre_deploy_{stamp}.sql"

env = os.environ.copy()
password = db.get("PASSWORD") or ""
if password:
    env["PGPASSWORD"] = password

cmd = [
    "pg_dump",
    "-h", str(db.get("HOST") or "127.0.0.1"),
    "-p", str(db.get("PORT") or "5432"),
    "-U", str(db.get("USER") or "postgres"),
    "-d", str(db.get("NAME") or "postgres"),
    "-f", str(outfile),
]
subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL)
print(f"[deploy] backup saved: {outfile}")
PY
}

optional_db_backup

log "Verifying production database is not Render"
"$PYTHON" <<'PY'
import os
import sys
from urllib.parse import urlsplit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

raw = (os.getenv("DATABASE_URL") or "").strip()
host = ""
if raw:
    host = (urlsplit(raw).hostname or "").strip().lower()
else:
    host = (os.getenv("DB_HOST") or "").strip().lower()

markers = ("render.com",)
if host.startswith("dpg-") or any(m in host for m in markers):
    print(
        f"[deploy] ERROR: database host '{host}' is Render. "
        "Update EC2 .env to AWS PostgreSQL (typically 127.0.0.1) "
        "and remove DATABASE_URL pointing at *.render.com.",
        file=sys.stderr,
    )
    raise SystemExit(1)
print(f"[deploy] database host ok: {host or '(components/unknown)'}")
PY

log "Database readiness probe (AWS Postgres)"
READY_ATTEMPTS=8
READY_SLEEP=3
ready=0
for attempt in $(seq 1 "$READY_ATTEMPTS"); do
  if "$PYTHON" manage.py check --database default; then
    ready=1
    break
  fi
  log "Database not ready (attempt ${attempt}/${READY_ATTEMPTS}) — retrying in ${READY_SLEEP}s"
  sleep "$READY_SLEEP"
done
[ "$ready" = "1" ] || fail "Database readiness check failed against AWS Postgres"

log "Ensuring persistent media directory exists"
"$PYTHON" <<'PY'
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings

media = Path(settings.MEDIA_ROOT)
media.mkdir(parents=True, exist_ok=True)
print(f"[deploy] MEDIA_ROOT={media}")
PY

log "Running Django system check"
"$PYTHON" manage.py check

log "Checking migration consistency (no new migrations allowed in production)"
"$PYTHON" manage.py makemigrations --check --dry-run

log "Migration plan"
"$PYTHON" manage.py migrate --plan

log "Applying migrations"
"$PYTHON" manage.py migrate --noinput

log "Collecting static files"
"$PYTHON" manage.py collectstatic --noinput

log "Restarting service: ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active --quiet "$SERVICE_NAME" \
  || fail "Service ${SERVICE_NAME} is not active after restart"

if command -v nginx >/dev/null 2>&1; then
  log "Validating Nginx configuration"
  if sudo nginx -t; then
    sudo systemctl reload nginx || log "WARNING: nginx reload failed"
  else
    log "WARNING: nginx -t failed — skipping reload"
  fi
fi

log "Health check: ${BACKEND_HEALTH_URL}"
curl --fail --silent --show-error --retry 10 --retry-delay 3 "$BACKEND_HEALTH_URL" >/dev/null \
  || fail "Health check failed for ${BACKEND_HEALTH_URL}"

log "Deployment succeeded"
log "Previous commit: ${PREVIOUS_COMMIT}"
log "Deployed commit: ${DEPLOYED_COMMIT}"
