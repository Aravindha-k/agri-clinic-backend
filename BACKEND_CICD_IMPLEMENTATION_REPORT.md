# Backend CI/CD Implementation Report

**Date:** 12 July 2026  
**Repository:** Kavya Agri Clinic Django backend  
**Status:** Workflow drafted — server setup required

---

## 1. Existing deployment method found

| Path | Method |
|------|--------|
| **EC2 production** (operator-confirmed) | Manual Git/SSH at `/var/www/agri-backend/agri-clinic-backend`, Gunicorn + PostgreSQL on localhost |
| **Render** (`render.yaml`) | PaaS auto-deploy from `main` — separate from EC2 |
| **Docker Compose** | Local/dev multi-container stack |

No automated EC2 deploy existed in the repository before this work.

---

## 2. Existing workflow found

| Workflow | Status |
|----------|--------|
| Backend GitHub Actions | **Not found** → created |
| Mobile GitHub Actions | **Not in this repo** (referenced by operator as separate) |

---

## 3. Files changed / added

| File | Purpose |
|------|---------|
| `.github/workflows/backend-ci.yml` | PR + push validation |
| `.github/workflows/backend-deploy.yml` | Manual SSH deploy (`workflow_dispatch` only) |
| `scripts/deploy_production.sh` | Safe EC2 Git deploy script |
| `scripts/run_ci_tests.sh` | Explicit Django test labels for CI |
| `BACKEND_CICD_AUDIT.md` | Pre-implementation audit |
| `BACKEND_CICD_SERVER_SETUP.md` | One-time EC2 + GitHub secrets setup |
| `BACKEND_DEPLOYMENT_ROLLBACK.md` | Rollback and backup procedures |
| `BACKEND_CICD_IMPLEMENTATION_REPORT.md` | This report |

---

## 4. Required GitHub secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `EC2_HOST` | Yes | EC2 hostname or IP |
| `EC2_PORT` | Yes | SSH port (usually `22`) |
| `EC2_USER` | Yes | Deploy user (e.g. `deploy`) |
| `EC2_SSH_PRIVATE_KEY` | Yes | Private key for Actions |
| `EC2_KNOWN_HOSTS` | Yes | Verified `ssh-keyscan` output |
| `BACKEND_DEPLOY_PATH` | Yes | `/var/www/agri-backend/agri-clinic-backend` |
| `BACKEND_SERVICE_NAME` | Yes | systemd unit name |
| `BACKEND_HEALTH_URL` | Yes | e.g. `http://127.0.0.1:8000/healthz/` |
| `DEPLOY_BRANCH` | Optional | Default `main` |

Use GitHub **environment: production** with protection rules for deploy approval.

---

## 5. One-time EC2 commands (summary)

See `BACKEND_CICD_SERVER_SETUP.md` for full detail.

1. Confirm systemd service name
2. Ensure clean Git checkout on `main`
3. Create `deploy` user + SSH authorized key
4. Configure minimal sudoers for `systemctl restart/is-active` only
5. Configure GitHub secrets
6. Manual dry-run: `bash scripts/deploy_production.sh`
7. First `workflow_dispatch` deploy from Actions

---

## 6. Service name

**Unresolved placeholder** — must be confirmed on EC2:

```bash
systemctl list-units --type=service | grep -Ei 'gunicorn|agri|django|uvicorn'
```

Store result in `BACKEND_SERVICE_NAME`. Example placeholder only: `agri-backend.service`.

---

## 7. CI checks

On pull requests and pushes to `main`:

1. Checkout
2. Python **3.12** + pip cache
3. `pip install -r requirements.txt`
4. `python manage.py check`
5. `python manage.py makemigrations --check --dry-run`
6. `migrate --noinput` against PostgreSQL 15 service container
7. `bash scripts/run_ci_tests.sh --verbosity 2`

No lint/type/security tools configured in repo — not run.

Test env (not production):

```text
DATABASE_URL=postgres://postgres:postgres@localhost:5432/agri_test
SECRET_KEY=ci-only-secret-key-not-for-production
APP_ENV=local
```

---

## 8. Deployment sequence

GitHub Actions (`backend-deploy.yml`, manual trigger):

1. Resolve and validate `commit_sha`
2. SSH with strict host key checking
3. Run `scripts/deploy_production.sh` on EC2 with env vars

On EC2 (`deploy_production.sh`):

1. Verify `.env`, `.venv`, Git repo
2. Block unexpected dirty working tree
3. `git fetch` + `git merge --ff-only $DEPLOY_COMMIT`
4. Optional `pg_dump` backup
5. `pip install -r requirements.txt`
6. `manage.py check`
7. `makemigrations --check --dry-run`
8. `migrate --plan` + `migrate --noinput`
9. `collectstatic --noinput`
10. `sudo systemctl restart $SERVICE_NAME`
11. `curl --fail --retry` health URL
12. Log previous and deployed SHAs

---

## 9. Migration behavior

| Phase | Command | Production? |
|-------|---------|-------------|
| CI | `makemigrations --check --dry-run` | No |
| Deploy | `migrate --plan` (logged) | Yes |
| Deploy | `migrate --noinput` | Yes |
| Forbidden | `makemigrations` | Never on production |

Failed migration → script exits before/alongside service restart; operator follows rollback doc.

---

## 10. Health-check behavior

Endpoint: `GET /healthz/`

- **200** + `"status":"ok"` + `"database":"ok"` → deploy success
- **503** + `"database":"error"` → deploy fails health step
- No authentication required
- No secrets in response

Default probe URL on server: `http://127.0.0.1:8000/healthz/` (adjust if Gunicorn port differs).

---

## 11. Rollback procedure

Documented in `BACKEND_DEPLOYMENT_ROLLBACK.md`:

- Record previous/new SHA and migration state
- Code rollback via redeploy of previous SHA (ff-only)
- DB restore from `backups/deploy/pre_deploy_*.sql` when schema incompatible
- Do not auto-reverse migrations unless explicitly tested

---

## 12. Security controls

| Control | Implementation |
|---------|----------------|
| Secrets in GitHub Secrets only | Yes |
| Strict SSH host verification | `StrictHostKeyChecking=yes`, `EC2_KNOWN_HOSTS` |
| No `StrictHostKeyChecking=no` | Enforced |
| Production `.env` preserved | Not touched by deploy script |
| Minimal sudo | Documented sudoers snippet |
| No production DB in CI | PostgreSQL service container |
| Manual-first deploy | `workflow_dispatch` only; auto trigger commented out |
| Dirty tree guard | Deploy aborts on unexpected changes |
| No blind `git reset --hard` | Uses `merge --ff-only` to exact commit |

---

## 13. Tests run (local validation)

| Command | Result |
|---------|--------|
| `python manage.py check` | Pass |
| `python manage.py makemigrations --check --dry-run` | Pass (no changes) |
| `python manage.py migrate --plan` | Pass (no pending ops) |
| `bash -n scripts/deploy_production.sh` | To run before commit |
| `bash -n scripts/run_ci_tests.sh` | To run before commit |
| Selected Django tests (18 cases) | Pass |
| Full `manage.py test` discover | Windows local conflict with global `tests` module — CI uses Linux + explicit labels |

---

## 14. Items requiring manual confirmation

- [ ] Exact **systemd service name** on EC2
- [ ] Gunicorn **bind port** for health URL
- [ ] **Nginx** present and whether public health URL differs from localhost
- [ ] **Celery** workers — separate restart policy if needed
- [ ] EC2 Git working tree is **clean**
- [ ] Python version alignment (`runtime.txt` says 3.10; EC2 operator cited 3.12)
- [ ] All GitHub **secrets** configured
- [ ] **sudoers** file installed and validated
- [ ] First **manual** `workflow_dispatch` deploy succeeds
- [ ] Render deploy (if still active) — ensure EC2 and Render are intentionally separate targets

---

## 15. Final readiness verdict

### **Workflow drafted — server setup required**

Automatic deployment from `main` is **disabled** until:

1. EC2 secrets and sudo are configured
2. Service name and health URL are confirmed
3. One successful **manual** GitHub Actions deploy completes

After that, uncomment the `workflow_run` block in `.github/workflows/backend-deploy.yml` to enable auto-deploy after CI passes.

**Not pushed or deployed** per implementation instructions — awaiting operator approval.

---

## Commit strategy (planned)

1. `ci(backend): add Django validation workflow`
2. `ci(backend): add secure EC2 deployment workflow`
3. `docs(backend): document deployment setup and rollback`
