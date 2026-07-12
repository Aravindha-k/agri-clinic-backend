# Backend CI/CD — One-Time EC2 Server Setup

This guide configures Ubuntu EC2 for **Git-based SSH deployment** from GitHub Actions.  
Production path (confirmed): `/var/www/agri-backend/agri-clinic-backend`

---

## Prerequisites

- Ubuntu EC2 with Django already running
- PostgreSQL on `127.0.0.1`
- Git repository cloned at the deploy path
- Python virtualenv at `.venv/`
- Production `.env` present **only on the server** (never committed)

---

## 1. Confirm service name and process model

Run on EC2 as an administrator:

```bash
systemctl list-units --type=service | grep -Ei 'gunicorn|agri|django|uvicorn'
ps -ef | grep -E 'gunicorn|uvicorn|daphne' | grep -v grep
systemctl list-unit-files | grep -Ei 'gunicorn|agri|django'
```

Record the **exact** systemd unit name (example placeholder only):

```text
agri-backend.service
```

Store it in GitHub secret `BACKEND_SERVICE_NAME`.

If Celery workers exist as separate units, document them — the current deploy script restarts **only** the web backend service.

---

## 2. Confirm Git checkout is clean

```bash
cd /var/www/agri-backend/agri-clinic-backend
git status
git remote -v
git branch --show-current
```

Requirements:

- Remote points to `https://github.com/Aravindha-k/agri-clinic-backend.git` (or your fork)
- Branch is `main`
- No unexpected tracked modifications (see allow-list in `scripts/deploy_production.sh`)

Resolve any drift **before** enabling GitHub Actions deploy.

---

## 3. Create a dedicated deploy user (recommended)

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG www-data deploy   # adjust group if your app user differs
```

Grant ownership/read on the project tree:

```bash
sudo chown -R deploy:www-data /var/www/agri-backend/agri-clinic-backend
sudo chmod -R g+rX /var/www/agri-backend/agri-clinic-backend
```

Ensure `.env` is readable by `deploy` but not world-readable:

```bash
sudo chmod 640 /var/www/agri-backend/agri-clinic-backend/.env
sudo chown deploy:www-data /var/www/agri-backend/agri-clinic-backend/.env
```

---

## 4. SSH key for GitHub Actions

On your **local admin machine** (not committed to Git):

```bash
ssh-keygen -t ed25519 -C "github-actions-agri-backend" -f ./agri-backend-deploy -N ""
```

On EC2, install the **public** key:

```bash
sudo mkdir -p /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh
sudo tee -a /home/deploy/.ssh/authorized_keys < agri-backend-deploy.pub
sudo chown -R deploy:deploy /home/deploy/.ssh
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

Verify host key independently (compare fingerprint out-of-band), then capture:

```bash
ssh-keyscan -p 22 YOUR_EC2_PUBLIC_IP
```

Store output in GitHub secret `EC2_KNOWN_HOSTS`.

---

## 5. Minimal sudoers (no password for specific commands only)

Create `/etc/sudoers.d/agri-backend-deploy`:

```sudoers
# GitHub Actions deploy user — restart backend only
deploy ALL=NOPASSWD: /bin/systemctl restart agri-backend.service
deploy ALL=NOPASSWD: /bin/systemctl is-active agri-backend.service
```

Replace `agri-backend.service` with your confirmed unit name.

Validate:

```bash
sudo visudo -cf /etc/sudoers.d/agri-backend-deploy
```

**Do not** use `NOPASSWD: ALL`.

---

## 6. GitHub repository secrets

Configure under **Settings → Secrets and variables → Actions** (environment: `production` recommended).

| Secret | Example / notes |
|--------|-----------------|
| `EC2_HOST` | EC2 public IP or DNS |
| `EC2_PORT` | `22` |
| `EC2_USER` | `deploy` |
| `EC2_SSH_PRIVATE_KEY` | Contents of `agri-backend-deploy` (private key) |
| `EC2_KNOWN_HOSTS` | Output of verified `ssh-keyscan` |
| `BACKEND_DEPLOY_PATH` | `/var/www/agri-backend/agri-clinic-backend` |
| `BACKEND_SERVICE_NAME` | Confirmed systemd unit, e.g. `agri-backend.service` |
| `BACKEND_HEALTH_URL` | `http://127.0.0.1:8000/healthz/` (localhost) or public URL |
| `DEPLOY_BRANCH` | `main` (optional) |

Never store `DATABASE_URL`, `SECRET_KEY`, or `.env` contents in GitHub.

---

## 7. Health check URL

Preferred on-server probe (bypasses Nginx/TLS issues):

```text
http://127.0.0.1:8000/healthz/
```

Expected:

```json
{"status": "ok", "database": "ok"}
```

If Gunicorn listens on a different port, adjust `BACKEND_HEALTH_URL`.

---

## 8. Manual deploy dry run (on EC2)

After merging CI/CD files to `main`:

```bash
cd /var/www/agri-backend/agri-clinic-backend
git pull origin main
chmod +x scripts/deploy_production.sh

export DEPLOY_COMMIT="$(git rev-parse origin/main)"
export DEPLOY_PATH="/var/www/agri-backend/agri-clinic-backend"
export SERVICE_NAME="agri-backend.service"   # replace
export BACKEND_HEALTH_URL="http://127.0.0.1:8000/healthz/"

bash scripts/deploy_production.sh
```

---

## 9. First GitHub Actions deploy

1. Configure all secrets above
2. Ensure **Backend CI** passes on `main`
3. Run **Backend Deploy** → `workflow_dispatch` → environment `production`
4. Optionally pin `commit_sha` to a known-good SHA
5. Review Actions logs and EC2 `journalctl`

Only after success, consider enabling automatic deploy (uncomment `workflow_run` in `backend-deploy.yml`).

---

## 10. Post-deploy log inspection

```bash
journalctl -u agri-backend.service -n 200 --no-pager
journalctl -u agri-backend.service -f
```

If Nginx is used:

```bash
sudo tail -n 200 /var/log/nginx/error.log
sudo tail -n 200 /var/log/nginx/access.log
```

Restart Nginx **only** when site configs change:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 11. Firewall and connectivity

- GitHub Actions runners must reach EC2 SSH (`EC2_PORT`, usually 22)
- Restrict SSH source IPs in the EC2 security group when possible
- Do not expose PostgreSQL publicly

---

## Related files

- `BACKEND_CICD_AUDIT.md` — architecture audit
- `scripts/deploy_production.sh` — deploy script executed on EC2
- `.github/workflows/backend-ci.yml` — validation pipeline
- `.github/workflows/backend-deploy.yml` — SSH deploy (manual-first)
- `BACKEND_DEPLOYMENT_ROLLBACK.md` — rollback procedure
