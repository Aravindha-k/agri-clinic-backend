# Attendance Release — GO / NO-GO Checklist

Backend `feature/attendance-phase2` (@ `30cb890`, migrations `attendance`
0001–0003) + frontend `feature/attendance-admin-phase3` (@ `b1472a02`).
Production baseline: `6df82fc` on EC2 `13.207.17.117`.

## Backend — pre-merge

- [ ] `feature/attendance-phase2` merges cleanly to `main` (no conflicts).
- [ ] Local uncommitted changes (`api/admin/views.py`, `reports/*`,
      `masters/*`) are **excluded** — they are unrelated and must not ride
      along. Verify with `git status` before committing the merge.
- [ ] `python manage.py makemigrations --check --dry-run` clean on merged main.
- [ ] Attendance test suite green (64/64 on the branch).
- [ ] This deploy-safety branch (mandatory backup in `backend-deploy.yml` +
      `deploy_production.sh`) is merged **first or together** — never deploy
      attendance with the old backup-less workflow.

## Backend — deploy day

- [ ] Off-server encrypted backup taken and restore-verified on a scratch DB
      (`docs/BACKUP_AND_RESTORE.md`) **before** the deploy workflow runs.
- [ ] Deploy runs to a green `healthz`; `showmigrations attendance` shows
      `[X] 0001`–`[X] 0003`.
- [ ] `GET /api/v1/admin/attendance/shops/` returns 401/403 (auth wired, not 404).
- [ ] `POST /api/v1/attendance/check-in/` returns `403 TEST_MODE_DISABLED`
      — confirms `ATTENDANCE_TEST_MODE_ENABLED` is unset/false in prod `.env`.
- [ ] Smoke: dashboard, visits, farmers, tracking pages still load.

## Frontend — release

- [ ] `feature/attendance-admin-phase3` built (`npm run build` clean) and
      deployed to `/var/www/agri-admin/agri-clinic-frontend/dist`.
- [ ] Sidebar "Attendance" visible to staff admins; hidden nav changes are
      additive only.
- [ ] Admin panel: create TEST shop → create test employee → assign →
      register TEST device → copy one-time token shown in modal.

## Pilot gating (deliberate, reversible)

- [ ] Device check-in pilot ONLY: set `ATTENDANCE_TEST_MODE_ENABLED=true` in
      server `.env`, restart `agri-backend.service`, run test check-in/out
      with the test device token, verify event shows `TEST / MANUAL` badge.
- [ ] After pilot: revert flag to `false`, restart, confirm 403 again.
- [ ] Decision recorded whether flag stays on for an approved pilot window.

## Rollback readiness

- [ ] Previous SHA `6df82fc` noted; redeploy-by-SA path rehearsed.
- [ ] `migrate attendance zero` identified as the schema-only rollback.
- [ ] Latest verified backup file path + offsite location recorded.

## Hard NO-GO conditions (any one blocks release)

- Backup creation or verification fails, or no off-server copy exists.
- Unrelated uncommitted changes leak into the merge.
- `makemigrations --check` reports missing migrations.
- `TEST_MODE_DISABLED` check does NOT return 403 in prod.
- Any regression in Field Officer / GPS / farmer / visit smoke tests.
- Frontend bundle not built from the reviewed commit.
