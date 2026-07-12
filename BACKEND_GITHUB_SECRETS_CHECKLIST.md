# Backend GitHub Secrets Checklist

Add these in GitHub before running **Backend Deploy**.

**Path:** GitHub repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Use a **production** environment with approval rules if available.

Do **not** paste real secret values into documentation, tickets, or chat.

---

## Required secrets

| Secret | Example format | Where to get it | Sensitive |
|--------|----------------|-----------------|-----------|
| `EC2_HOST` | `203.0.113.10` or `api.yourdomain.com` | AWS EC2 console → instance public IP or DNS | No |
| `EC2_PORT` | `22` | EC2 security group SSH port (usually 22) | No |
| `EC2_USER` | `ubuntu` | EC2 discovery block → `whoami` | No |
| `EC2_SSH_PRIVATE_KEY` | `-----BEGIN OPENSSH PRIVATE KEY-----` … | Generated locally with `ssh-keygen`; public half on EC2 `authorized_keys` | **Yes** |
| `EC2_KNOWN_HOSTS` | `203.0.113.10 ssh-ed25519 AAAA…` | `ssh-keyscan -p 22 YOUR_EC2_IP` after verifying fingerprint independently | No |
| `BACKEND_DEPLOY_PATH` | `/var/www/agri-backend/agri-clinic-backend` | Confirmed production path | No |
| `BACKEND_SERVICE_NAME` | `agri-backend.service` | EC2 discovery → `systemctl list-units` — **never guess** | No |
| `BACKEND_HEALTH_URL` | `http://127.0.0.1:8000/healthz/` or `https://api.yourdomain.com/healthz/` | EC2 discovery → curl that returns HTTP 200 | No |

### Optional

| Secret | Example | Notes |
|--------|---------|-------|
| `DEPLOY_BRANCH` | `main` | Defaults to `main` if omitted |

---

## Secret details

### `EC2_HOST`

- EC2 **public IP** or **DNS name**
- Must be reachable from GitHub Actions runners on the SSH port

### `EC2_PORT`

- Usually **`22`**
- Must match the EC2 security group inbound rule

### `EC2_USER`

- Usually **`ubuntu`** on Ubuntu AMIs
- Must match the Linux user whose `authorized_keys` contains the deploy public key
- Must match the sudoers `<DEPLOY_USER>` entry

### `EC2_SSH_PRIVATE_KEY`

- The **private** half of the deployment key pair
- Paste the **entire** key including `BEGIN` / `END` lines
- **Never** commit to Git or share in Slack/email

### `EC2_KNOWN_HOSTS`

- Output of `ssh-keyscan` for your server
- Verify the host fingerprint through AWS console or your team's records first
- Enables strict host-key checking (required — do **not** disable SSH host verification)

### `BACKEND_DEPLOY_PATH`

- Fixed path: `/var/www/agri-backend/agri-clinic-backend`
- Must contain `.git`, `.venv`, `.env`, and `scripts/deploy_production.sh` after first pull

### `BACKEND_SERVICE_NAME`

- Discovered from EC2, e.g. `gunicorn.service` or `agri-backend.service`
- Used by `sudo systemctl restart` in the deploy script
- Wrong name = deploy fails at service restart (safe failure)

### `BACKEND_HEALTH_URL`

- URL that returns **HTTP 200** with JSON like `{"status":"ok","database":"ok"}`
- Prefer on-server probe: `http://127.0.0.1:8000/healthz/` (adjust port if needed)
- Public HTTPS URL works if Nginx proxies `/healthz/` correctly

---

## Checklist before first deploy

- [ ] All 8 required secrets created
- [ ] EC2 discovery block output saved
- [ ] `BACKEND_SERVICE_NAME` matches `systemctl` output exactly
- [ ] Sudoers file validated with `sudo visudo -c`
- [ ] **Backend CI** workflow passed on `main`
- [ ] `git status --short` on EC2 shows no unexpected files

---

## Related docs

- `BACKEND_CICD_NEXT_STEPS.md` — step-by-step user guide
- `BACKEND_CICD_SERVER_SETUP.md` — EC2 discovery and sudoers
- `BACKEND_DEPLOYMENT_ROLLBACK.md` — if deploy fails
