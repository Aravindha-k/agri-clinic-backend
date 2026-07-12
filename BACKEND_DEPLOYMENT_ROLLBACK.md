# Backend Deployment Rollback

Procedures for recovering from a failed or bad Kavya Agri Clinic backend deployment on EC2.

---

## Record every deployment

Before and after each deploy, capture:

| Field | Source |
|-------|--------|
| Previous commit SHA | `git rev-parse HEAD` before deploy |
| Target commit SHA | GitHub Actions input / `DEPLOY_COMMIT` |
| Deployed commit SHA | `git rev-parse HEAD` after deploy |
| Migration state | `python manage.py showmigrations --plan` |
| Service status | `systemctl is-active <service>` |
| Health result | `curl -sf BACKEND_HEALTH_URL` |

The deploy script logs previous and deployed SHAs on success.

---

## When to rollback code only

Safe when:

- New migrations were **backward-compatible** or **not yet applied**
- Health check fails but database schema unchanged
- Application error introduced in Python/templates only

**Not safe** when destructive or irreversible migrations already applied — see [Migration rollback](#migration-rollback).

---

## Code rollback procedure

On EC2:

```bash
cd /var/www/agri-backend/agri-clinic-backend
source .venv/bin/activate

PREVIOUS_SHA="<commit-before-deploy>"
export DEPLOY_COMMIT="$PREVIOUS_SHA"
export DEPLOY_PATH="/var/www/agri-backend/agri-clinic-backend"
export SERVICE_NAME="agri-backend.service"   # confirmed name
export BACKEND_HEALTH_URL="http://127.0.0.1:8000/healthz/"
export RUN_DB_BACKUP=false                     # usually skip on rollback

git fetch origin main
git cat-file -e "${PREVIOUS_SHA}^{commit}"

bash scripts/deploy_production.sh
```

If `deploy_production.sh` refuses due to dirty tree, resolve server-local files first (never delete `.env`, `media/`, or `backups/`).

Alternative manual sequence:

```bash
git fetch origin main
git checkout main
git merge --ff-only "$PREVIOUS_SHA"
pip install -r requirements.txt
python manage.py check
python manage.py migrate --noinput    # only if compatible
python manage.py collectstatic --noinput
sudo systemctl restart agri-backend.service
curl -sf http://127.0.0.1:8000/healthz/
```

---

## Migration rollback

**Default policy:** do **not** auto-reverse migrations in production.

| Situation | Action |
|-----------|--------|
| Migration not yet applied | Roll back code; skip migrate |
| Backward-compatible migration applied | Roll back code; old code should still run |
| Destructive migration applied | **Stop.** Restore DB from backup; do not blindly revert code |
| Migration failed mid-deploy | Service should not have restarted; fix forward or restore DB |

Never run `makemigrations` on production.

---

## Database backup and restore

### Automatic pre-deploy backup

When `RUN_DB_BACKUP=true` (default), `scripts/deploy_production.sh` writes:

```text
backups/deploy/pre_deploy_YYYYMMDD_HHMMSS.sql
```

Requires `pg_dump` on PATH and PostgreSQL credentials from server `.env` (via Django settings — not printed).

### Manual backup

```bash
cd /var/www/agri-backend/agri-clinic-backend
source .venv/bin/activate
mkdir -p backups/manual
python manage.py shell -c "
import os, subprocess, datetime
from pathlib import Path
from django.conf import settings
db = settings.DATABASES['default']
out = Path('backups/manual') / f'manual_{datetime.datetime.utcnow():%Y%m%d_%H%M%S}.sql'
env = os.environ.copy()
env['PGPASSWORD'] = db.get('PASSWORD') or ''
subprocess.run(['pg_dump','-h',db['HOST'],'-p',str(db['PORT']),'-U',db['USER'],'-d',db['NAME'],'-f',str(out)], env=env, check=True)
print(out)
"
```

### Restore (destructive — requires maintenance window)

```bash
# Stop app first
sudo systemctl stop agri-backend.service

psql -h 127.0.0.1 -U agri_user -d agri_clinic_db -f backups/deploy/pre_deploy_YYYYMMDD_HHMMSS.sql

# Redeploy known-good commit, then start
sudo systemctl start agri-backend.service
```

Adjust user/database names to match server `.env`.

### Retention

- Keep at least **7 days** of deploy backups on disk
- Copy critical backups off-server (S3 or operator workstation)
- Never commit backup files to Git

---

## Health check failure after deploy

1. Check service: `systemctl status agri-backend.service`
2. Logs: `journalctl -u agri-backend.service -n 200 --no-pager`
3. Django check: `python manage.py check`
4. DB: `curl -sf http://127.0.0.1:8000/healthz/` — if `database: error`, inspect Postgres
5. If app code regression and DB compatible → [code rollback](#code-rollback-procedure)
6. If schema incompatible → restore DB backup + rollback code

GitHub Actions will fail the workflow when health check fails; EC2 may be left on new code with a stopped/unhealthy service — treat as incident.

---

## GitHub Actions re-deploy

To redeploy a known-good commit without SSH:

1. Actions → **Backend Deploy** → Run workflow
2. Set `commit_sha` to the verified SHA
3. Environment: `production`

---

## Security reminders

- Do not paste `.env`, `DATABASE_URL`, or private keys into tickets or GitHub issues
- Do not commit rollback backups
- Verify SSH host keys when rebuilding `EC2_KNOWN_HOSTS`

---

## Related documents

- `BACKEND_CICD_SERVER_SETUP.md` — initial setup
- `BACKEND_CICD_AUDIT.md` — architecture
- `scripts/deploy_production.sh` — automated deploy sequence
