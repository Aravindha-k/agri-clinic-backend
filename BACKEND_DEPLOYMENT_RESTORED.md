# Backend deployment — AWS EC2 is production

## Production architecture (current)

| Component | Location |
|-----------|----------|
| Django / Gunicorn | AWS EC2 (`/var/www/agri-backend/agri-clinic-backend`) |
| PostgreSQL | Same EC2 host (`127.0.0.1:5432`) via server `.env` |
| Media files | Persistent EC2 path (`MEDIA_ROOT`, e.g. `/var/www/agri-backend/media`) |
| Admin + mobile API | Same AWS backend |
| Deploy | `scripts/deploy_production.sh` + `.github/workflows/backend-deploy.yml` |

Public health probe (example): `http://13.207.17.117/healthz/` → `{"status":"ok","database":"ok"}`.

## What was wrong

`render.yaml` had `autoDeployTrigger: commit`, so every push to `main` also
deployed on **Render**. Render Dashboard `DATABASE_URL` pointed at:

`dpg-d84t75d7vvec73fhlpfg-a.singapore-postgres.render.com`

That produced deploy logs like `DATABASE_URL host=…render.com` and SSL failures.
That path is **not** AWS production.

## Fix applied in repo

- `render.yaml` → `autoDeployTrigger: off` (archived; do not re-enable for prod)
- Restored `.github/workflows/backend-deploy.yml` (manual `workflow_dispatch`)
- `scripts/deploy_production.sh` refuses Render DB hosts, probes DB readiness,
  ensures `MEDIA_ROOT`, migrates, restarts systemd, reloads Nginx
- Production settings refuse Render Postgres unless `RENDER=true` / `APP_ENV=render`

## Required on the EC2 server (operator)

1. Ensure `.env` uses local Postgres (`127.0.0.1`), **not** Render.
2. Prefer `DB_*` components or `DATABASE_URL=…@127.0.0.1:5432/…` with `DB_SSL_REQUIRE=false`.
3. Set `MEDIA_ROOT` to a persistent directory (not deleted by git).
4. Nginx `location /media/ { alias …; }` pointing at that directory.
5. Run deploy (Actions **Backend Deploy** or on-server `deploy_production.sh`).

## Obsolete

- Render Blueprint auto-deploy
- `docs/RENDER_DEPLOYMENT.md` (historical only)
- Render Dashboard `DATABASE_URL` for production traffic
