# Backend CI/CD — What To Do Next

Simple step-by-step guide for Kavya Agri Clinic backend deployment.  
**Automatic deployment is OFF** until you complete one successful manual deploy.

---

## Stage 1 — Push CI/CD code to GitHub

On your Windows PC:

```powershell
cd d:\agri_clinic
git status
git log -5 --oneline
git push origin main
```

You should see 3 (or more) CI/CD commits including:

- `ci(backend): add Django validation workflow`
- `ci(backend): add secure EC2 deployment workflow`
- `docs(backend): document deployment setup and rollback`

---

## Stage 2 — Confirm GitHub CI passes

1. Open GitHub → your repository → **Actions**
2. Click **Backend CI**
3. Wait for the latest run on `main` to finish **green**

If CI fails, **stop here** and fix the failure before continuing.

---

## Stage 3 — Discover EC2 service details

1. SSH into your EC2 server
2. Paste the **entire discovery block** from `BACKEND_CICD_SERVER_SETUP.md` (Step 0)
3. Save the full output

**Copy these values for later:**

| From output | Secret / config |
|-------------|-----------------|
| `whoami` | `EC2_USER` |
| Line from `systemctl list-units` ending in `.service` | `BACKEND_SERVICE_NAME` |
| `which systemctl` | sudoers file |
| `git status --short` | must be clean or only safe runtime files |
| Health URL returning **HTTP 200** | `BACKEND_HEALTH_URL` |

If `git status` shows unexpected files, read the “Safe vs blocking” table in `BACKEND_CICD_SERVER_SETUP.md` before deploying.

---

## Stage 4 — Configure GitHub secrets

1. GitHub → **Settings** → **Secrets and variables** → **Actions**
2. Add all 8 secrets listed in `BACKEND_GITHUB_SECRETS_CHECKLIST.md`:

   - `EC2_HOST`
   - `EC2_PORT`
   - `EC2_USER`
   - `EC2_SSH_PRIVATE_KEY`
   - `EC2_KNOWN_HOSTS`
   - `BACKEND_DEPLOY_PATH`
   - `BACKEND_SERVICE_NAME`
   - `BACKEND_HEALTH_URL`

3. Do **not** store database passwords or `.env` contents in GitHub

---

## Stage 5 — Configure minimal sudoers on EC2

After you know the real service name:

```bash
sudo visudo -f /etc/sudoers.d/agri-backend-deploy
```

Paste (replace placeholders from discovery output):

```sudoers
ubuntu ALL=NOPASSWD: /usr/bin/systemctl restart YOUR-SERVICE-NAME.service
ubuntu ALL=NOPASSWD: /usr/bin/systemctl is-active YOUR-SERVICE-NAME.service
```

Validate:

```bash
sudo visudo -cf /etc/sudoers.d/agri-backend-deploy
```

---

## Stage 6 — First manual deployment

**Before this step:** pull CI/CD files on EC2 once if the deploy script is not on the server yet:

```bash
cd /var/www/agri-backend/agri-clinic-backend
git pull origin main
chmod +x scripts/deploy_production.sh
```

Then in GitHub:

1. **Actions** → **Backend Deploy**
2. **Run workflow**
3. Branch: `main`
4. Environment: `production`
5. **commit_sha:** paste the SHA from Stage 2 CI run (or leave empty for latest `main`)
6. Run

Watch the log. Deploy stops on any failure (dirty Git tree, migration error, health check, etc.).

---

## Stage 7 — Verify deployment on EC2

```bash
cd /var/www/agri-backend/agri-clinic-backend
git rev-parse HEAD
source .venv/bin/activate
python manage.py showmigrations | grep '\[ \]' || true
systemctl status YOUR-SERVICE-NAME.service --no-pager
journalctl -u YOUR-SERVICE-NAME.service -n 100 --no-pager
curl -i YOUR-BACKEND-HEALTH-URL
```

**Expected:** `HTTP/1.1 200` and JSON with `"status":"ok"`.

---

## Stage 8 — Enable automatic deployment (later only)

**Do not do this yet.**

After **one successful manual deploy**, a maintainer can uncomment the `workflow_run` block in `.github/workflows/backend-deploy.yml` so pushes to `main` deploy automatically after CI passes.

---

## Quick reference

| Question | Document |
|----------|----------|
| What secrets do I need? | `BACKEND_GITHUB_SECRETS_CHECKLIST.md` |
| EC2 discovery commands? | `BACKEND_CICD_SERVER_SETUP.md` Step 0 |
| Deploy failed — now what? | `BACKEND_DEPLOYMENT_ROLLBACK.md` |
| Full technical report? | `BACKEND_CICD_IMPLEMENTATION_REPORT.md` |
