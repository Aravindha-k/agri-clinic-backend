# Backup & Restore — Production PostgreSQL (EC2)

Scope: `agri_clinic_db` on PostgreSQL 16, host `127.0.0.1` on the EC2 instance.
Backend deploy path: `/var/www/agri-backend/agri-clinic-backend`.

## Automatic pre-deploy backup (mandatory)

Every deploy — via `.github/workflows/backend-deploy.yml` or
`scripts/deploy_production.sh` — now runs `scripts/pre_deploy_backup.sh`
**before any migration**. The deploy aborts if:

- `pg_dump -Fc` exits non-zero
- the dump file is missing or < 100 KB
- `pg_restore -l` fails or the TOC is missing core tables
  (users, employee profiles, villages, farmers, visits)
- the DB host resolves to a non-AWS (Render) host

Backups land in `backups/deploy/pre_deploy_<UTC>.dump` on the server
(gitignored — never committed).

**Deliberate override** (emergency hotfix only, never for migrations):
`SKIP_DB_BACKUP=YES` *and* `ALLOW_UNSAFE_DEPLOY=YES`. Both are required and
the override is logged loudly. `RUN_DB_BACKUP=false` alone now fails the deploy.

## Off-server backup procedure (operator, ~5 min)

Run before every migration deploy and weekly otherwise:

```bash
# 1. On EC2 — create a manual backup
cd /var/www/agri-backend/agri-clinic-backend
sudo -u ubuntu bash scripts/pre_deploy_backup.sh
# note the emitted BACKUP_FILE_PATH

# 2. From your workstation — pull it off the server
scp -i agri-clinic-key-openssh.pem \
  ubuntu@<EC2_HOST>:/var/www/agri-backend/agri-clinic-backend/backups/deploy/pre_deploy_<TS>.dump \
  ./offsite/pre_deploy_<TS>.dump

# 3. Encrypt before storing anywhere shared
openssl enc -aes-256-cbc -pbkdf2 -salt \
  -in pre_deploy_<TS>.dump -out pre_deploy_<TS>.dump.enc
rm pre_deploy_<TS>.dump   # keep only the encrypted copy

# 4. Store the .enc in two of: operator workstation, S3 bucket,
#    encrypted cloud drive. Record the passphrase in the password manager.
```

The existing `ops-operational-reset.yml` workflow already demonstrates an
automated variant: `scp` to runner → AES-256 encrypt with
`OPS_BACKUP_ENCRYPTION_KEY` → `upload-artifact` (14-day retention).

## Retention policy

| Tier | Location | Retention |
|---|---|---|
| Pre-deploy dumps | EC2 `backups/deploy/` | Last 10; prune older monthly |
| Manual/offsite encrypted | Operator workstation + S3/cloud | 90 days |
| Pre-incident / pre-reset dumps | S3/cloud | 1 year |
| Monthly snapshot | S3/cloud | 12 months |

Prune on-server (keeps newest 10):

```bash
cd /var/www/agri-backend/agri-clinic-backend/backups/deploy
ls -t pre_deploy_*.dump | tail -n +11 | xargs -r rm --
```

## Restore verification — scratch database only

NEVER restore over `agri_clinic_db`. Verify on a scratch DB:

```bash
# On EC2 (or a staging box) — NOT against production name
sudo -u postgres createdb agri_restore_test
pg_restore -d agri_restore_test \
  -h 127.0.0.1 -U <db_user> \
  --no-owner --no-privileges \
  backups/deploy/pre_deploy_<TS>.dump

# Sanity checks
sudo -u postgres psql -d agri_restore_test -c \
  "SELECT count(*) FROM auth_user; SELECT count(*) FROM masters_farmer;"

# Verify Django sees a coherent DB
DATABASE_URL=postgres://<user>:<pass>@127.0.0.1:5432/agri_restore_test \
  .venv/bin/python manage.py check --database default   # point settings at scratch DB

# Drop the scratch DB when done
sudo -u postgres dropdb agri_restore_test
```

Pass criteria: `pg_restore` exit 0, core table row counts > 0,
`manage.py check` clean against the scratch database.

## Emergency restore (production, only after approval)

1. `systemctl stop agri-backend.service`
2. Take a fresh `pg_dump` of the broken DB (post-incident backup).
3. `pg_restore -d agri_clinic_db --clean --if-exists --no-owner --no-privileges <dump>`
4. `systemctl start agri-backend.service`, curl `/healthz/`, spot-check admin login.

## Deploy serialization and migration gating

- `scripts/deploy_production.sh` takes a non-blocking `flock` on
  `/var/lock/agri-backend-deploy.lock` (override via `DEPLOY_LOCK_FILE`), so a
  manual deploy can never overlap a workflow deploy or another operator.
- The GitHub workflow additionally serializes runs via
  `concurrency: backend-deploy-production` (queued, not cancelled).
- Set `EXPECTED_PENDING_MIGRATIONS="attendance.0001_initial attendance.0002_attendance_employee attendance.0003_alter_attendanceauditlog_action"`
  before deploy to make the release abort if any other migration is pending.
