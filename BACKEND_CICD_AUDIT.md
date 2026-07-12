# Backend CI/CD Audit — Kavya Agri Clinic

**Audit date:** 12 July 2026  
**Repository:** `d:\agri_clinic` (GitHub: `Aravindha-k/agri-clinic-backend`)  
**Target production path (confirmed by operator):** `/var/www/agri-backend/agri-clinic-backend`

---

## Executive summary

| Question | Finding |
|----------|---------|
| Backend GitHub Actions workflow exists? | **No** — `.github/workflows/` is absent |
| Mobile GitHub Actions exists? | **Not in this repo** (mobile lives under `mobile/`; separate workflow referenced by operator) |
| Current production deploy method | **Manual Git operations on EC2** (inferred); Render blueprint also documented |
| Docker used in production on EC2? | **Unknown / likely no** — Docker Compose exists for local/dev stacks only |
| Production `.env` in Git? | **No** — `.env` is gitignored |
| Health endpoint safe for deploy checks? | **Yes** — `GET /healthz/` returns `{status, database}` without secrets |

**Verdict before changes:** Deployment is manual on EC2; CI/CD must be introduced. Render auto-deploy (`render.yaml`) is a separate hosting path and must not be conflated with EC2 production.

---

## Repository CI/CD inventory

### `.github/workflows/`

**Not present.** No backend CI or deploy automation in the repository today.

### Container / PaaS artifacts

| File | Purpose | Production EC2? |
|------|---------|-----------------|
| `Dockerfile` | Python 3.11-slim image, Gunicorn, collectstatic at build | Documented for container deploy, not confirmed on EC2 |
| `docker-compose.yml` | Local stack: Postgres 15, Redis, web, Celery | **Dev/local only** |
| `render.yaml` | Render web service auto-deploy from `main` | **Separate Render host** (`agri-clinic-backend.onrender.com`) |
| `build.sh` | Render build: pip + collectstatic | Render only |

### Deployment scripts

| File | Role |
|------|------|
| `build.sh` | Render build phase |
| `scripts/run_dev_server.ps1` | Local Windows dev (`--noreload`) |
| `scripts/render_db_sync.py` | Render DB backup/restore helper |
| `scripts/check_render_phase1.py` | Post-deploy Render smoke |

**No EC2 deploy script existed before this CI/CD work.**

### Systemd / Nginx / Gunicorn in repo

| Artifact | Found? |
|----------|--------|
| systemd unit files | **Not in repository** |
| Nginx site configs | **Not in repository** |
| Gunicorn config file | **Inline in** `render.yaml`, `Dockerfile`, `docker-compose.yml` only |

Operator must confirm the **actual systemd service name** on EC2 (placeholder: `BACKEND_SERVICE_NAME` secret).

### Documentation

| Doc | Deploy relevance |
|-----|------------------|
| `docs/RENDER_DEPLOYMENT.md` | Render PaaS flow, `/healthz/`, migrate + `verify_production_db` |
| `docs/LOCAL_SETUP.md` | Local dev only |
| `LOCAL_NETWORK_CONFIGURATION.md` | LAN testing |
| `.env.production.example` | EC2 template (`DB_*`, `STATIC_ROOT`, `MEDIA_ROOT`) |
| `docs/DELIVERABLES.md` | Generic deployment checklist |

**No EC2-specific runbook existed before this audit.**

---

## Application architecture (deployment-relevant)

### Stack

- **Django 5.2.10**, DRF, Gunicorn 24.x, WhiteNoise (static), optional Celery/Redis
- **Database:** PostgreSQL in production (`DATABASE_URL` or `DB_*` components); SQLite fallback only when non-production and no Postgres configured
- **Static files:** `collectstatic` → `STATIC_ROOT` (WhiteNoise `CompressedManifestStaticFilesStorage`)
- **Media:** `MEDIA_ROOT` on disk unless `USE_S3=true`

### Settings loader (`config/settings.py`)

- `load_dotenv(override=False)` — shell/GitHub/EC2 env wins over `.env`; **deploy must never overwrite server `.env`**
- `APP_ENV=production` (or `aws`) enables production security defaults
- Production requires `DATABASE_URL` or `DB_NAME` + `DB_USER` + `DB_HOST`
- `.env` is gitignored (`.gitignore` lines 1–6)

### Health check (`config/urls.py`)

```http
GET /healthz/
```

Response (no auth):

```json
{"status": "ok", "database": "ok"}
```

- HTTP **200** when DB `SELECT 1` succeeds
- HTTP **503** with `"status": "degraded"` when DB fails
- **Does not expose** credentials, URLs, or stack traces
- Covered by `config/tests/test_health_check.py`

**Safe for post-deploy verification** (use public URL or localhost behind Nginx).

### Gunicorn (documented commands)

Render:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120
```

Docker Compose: 4 workers, gthread, port 8000.

EC2 likely uses a similar Gunicorn command inside systemd — **name unconfirmed**.

### Nginx

Not defined in repo. Typical EC2 pattern (assumed, **unconfirmed**):

```
Client → Nginx (:443/:80) → Gunicorn (127.0.0.1:8000) → Django
```

Deploy workflow should **not** restart Nginx unless Nginx configs change.

---

## Branch and deploy model

| Item | Current state |
|------|---------------|
| Default branch | `main` |
| Render auto-deploy | `main` commits (Render service) |
| EC2 deploy | **Manual** (operator SSH + Git); no automation in repo |
| Recommended deploy branch | `main` |
| Server update method | **Git fetch/checkout** at `/var/www/agri-backend/agri-clinic-backend` (preferred over rsync/scp) |

No evidence of rsync/scp deploy scripts in the repository.

---

## Python version notes

| Source | Version |
|--------|---------|
| `runtime.txt` | **3.10.0** (Render hint) |
| `Dockerfile` | **3.11** |
| Operator EC2 note | **3.12** (unverified in repo) |
| Local dev (observed) | 3.10 |

**Action:** Align EC2 `.venv` Python with CI (3.12 recommended by operator). Update `runtime.txt` separately when confirmed.

---

## Test suite (CI implications)

- Tests live under `*/tests/` and `accounts/test_admin_security.py`
- `python manage.py test` (full discover) can fail on some environments due to a conflicting top-level `tests` module name on Windows
- Linux CI should use `scripts/run_ci_tests.sh` with explicit app labels
- CI must use **PostgreSQL service container**, not production DB
- No pytest/ruff/flake8 config in repo — CI runs Django checks + migration check + tests only

---

## Secrets and files that must never be deployed from Git

| Path / secret | Handling |
|---------------|----------|
| `.env` | Gitignored; **preserve on server** |
| `media/` | Gitignored; preserve uploads |
| `staticfiles/` | Generated on server via collectstatic |
| `backups/` | Gitignored; preserve |
| `db.sqlite3` | Gitignored; not used in EC2 production |
| SSH keys | GitHub Secrets only |

---

## Confirmed deployment architecture (EC2)

```
┌─────────────────┐     push/merge      ┌──────────────────┐
│ GitHub (main)   │ ──────────────────► │ GitHub Actions   │
└─────────────────┘                     │  CI: test/check  │
                                        │  Deploy: SSH     │
                                        └────────┬─────────┘
                                                 │ SSH (StrictHostKeyChecking)
                                                 ▼
                                        ┌──────────────────┐
                                        │ Ubuntu EC2       │
                                        │ /var/www/agri-   │
                                        │  backend/agri-   │
                                        │  clinic-backend  │
                                        │  .venv + .env    │
                                        │  PostgreSQL :5432│
                                        └────────┬─────────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────────┐
                    ▼                            ▼                            ▼
             git checkout                 pip install                  migrate +
             exact SHA                    requirements.txt            collectstatic
                    │                            │                            │
                    └────────────────────────────┴────────────────────────────┘
                                                 │
                                                 ▼
                                    systemctl restart <BACKEND_SERVICE_NAME>
                                                 │
                                                 ▼
                                    GET /healthz/ → 200 + database ok
```

**Unresolved until EC2 verification:**

1. Exact **systemd service name**
2. Whether **Nginx** terminates TLS/proxy
3. Whether **Celery** workers run as separate systemd units
4. Whether production Git working tree is **clean**

---

## Recommended next steps (implemented in follow-up files)

1. Add `backend-ci.yml` — validate on PR and push to `main`
2. Add `backend-deploy.yml` — **manual-only** (`workflow_dispatch`) until first successful deploy
3. Add `scripts/deploy_production.sh` — safe Git-based deploy on EC2
4. Document one-time server setup in `BACKEND_CICD_SERVER_SETUP.md`
5. Document rollback in `BACKEND_DEPLOYMENT_ROLLBACK.md`

**Do not enable automatic deploy from `main` until one manual `workflow_dispatch` succeeds.**
