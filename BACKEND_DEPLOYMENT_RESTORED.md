# Backend deployment — restored automatic path

## What Git history proves

| Path | Evidence | Automatic on `main` push? | GitHub EC2 secrets? |
|------|----------|---------------------------|---------------------|
| **Render** (`render.yaml`) | Added in `2f7b63f` (2026-04-10) with `autoDeployTrigger: commit` | **Yes** (Render GitHub integration) | **None** |
| **Backend CI** (`.github/workflows/backend-ci.yml`) | Added in `770e1c5` (2026-07-12) | Validates only — does not deploy | None for deploy |
| **Backend Deploy SSH** (`.github/workflows/backend-deploy.yml`) | Added in `55e1e58` (2026-07-12) | No (manual `workflow_dispatch` only) | Requires `EC2_HOST`, `EC2_USER`, `EC2_SSH_PRIVATE_KEY`, … |

There is **no** prior workflow in this repository that used:

- `runs-on: self-hosted`
- EC2 webhooks
- AWS CodeDeploy
- cron / systemd git-pull units (not in repo)

EC2 at `/var/www/agri-backend/agri-clinic-backend` was documented as **manual Git** (`BACKEND_CICD_AUDIT.md`). The SSH Actions workflow was a **new** method, not a replacement of an older Actions auto-deploy.

## Restored primary automatic deploy

- **Platform:** Render service `agri-clinic-backend`
- **Trigger:** push / commit on `main` (`autoDeployTrigger: commit`)
- **URL:** `https://agri-clinic-backend.onrender.com`
- **Secrets:** only in Render dashboard (`DATABASE_URL`, `SECRET_KEY`) — not GitHub Actions EC2 secrets

The SSH `Backend Deploy` workflow file has been **removed** so it is not a competing production path and cannot fail with `EC2_HOST secret is required`.

`scripts/deploy_production.sh` remains for **optional on-server** EC2 deploys when an operator already has SSH access to the machine (not via GitHub secrets).

## EC2 public IP (`13.207.17.117`)

That host is **not** Render. Restoring Render auto-deploy does **not** update the EC2 checkout. Live OpenAPI on that IP matches a pre-`55f368e` tree (no `/api/v1/mobile/bootstrap/`). Updating it requires an on-server:

```bash
cd /var/www/agri-backend/agri-clinic-backend
git fetch origin main
git merge --ff-only origin/main   # or exact SHA
# activate .venv, migrate, collectstatic, restart systemd unit
```

Do not point the mobile app at Render unless product owners intentionally switch production hosts.
