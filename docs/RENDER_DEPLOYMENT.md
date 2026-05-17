# Render Deployment Setup

## Service model

This repo uses a Render Blueprint file at [render.yaml](../render.yaml).

- Web service: `agri-clinic-backend`
- Runtime: Python
- Build: `pip install -r requirements.txt` + `collectstatic`
- Pre-deploy: `migrate` + `verify_production_db`
- Start: `gunicorn config.wsgi:application`
- Health check: `/healthz/`

## Database wiring (manual env — not Blueprint-linked)

`DATABASE_URL` is **not** auto-linked via `fromDatabase`. Set it explicitly on the web service so it cannot silently point at a retired database.

In **Render Dashboard → agri-clinic-backend → Environment**, set:

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | `postgresql://agri_clinic_db_user:<password>@dpg-d84t75d7vvec73fhlpfg-a/agri_clinic_db` |
| `RENDER_POSTGRES_HOST_SUFFIX` | `singapore-postgres.render.com` |
| `DB_SSL_REQUIRE` | `false` |

Copy the full connection string from your Render Postgres instance (`agri_clinic_db`), or from local `render.production.env` (gitignored).

**Remove** any old `DATABASE_URL` that uses host `dpg-d7ckj7dckfvc739s0frg-a` (retired/suspended). Production settings will refuse that host at startup.

## Required env vars on the web service

- `SECRET_KEY` (long random string; not `unsafe-secret`)
- `DEBUG=False`
- `APP_ENV=production`
- `ALLOWED_HOSTS=agri-clinic-backend.onrender.com,.onrender.com`
- `CORS_ALLOW_ALL_ORIGINS=false`
- `CORS_ALLOWED_ORIGINS=https://agri-clinic-frontend.onrender.com`
- `CSRF_TRUSTED_ORIGINS=https://agri-clinic-backend.onrender.com`

`render.yaml` sets `RENDER_POSTGRES_HOST_SUFFIX` in the Blueprint; `DATABASE_URL` and `SECRET_KEY` must be set in the dashboard (`sync: false`).

## Deploy flow

1. Update Environment variables (especially `DATABASE_URL`).
2. **Clear build cache** (Render → Manual Deploy → Clear build cache & deploy).
3. Push to `main` or trigger deploy.
4. Check deploy logs for `DATABASE_URL host:` and `verify_production_db` success.
5. Confirm `GET https://agri-clinic-backend.onrender.com/healthz/` returns `{"status":"ok"}`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Migrations fail / DB connection errors | Wrong `DATABASE_URL` in dashboard; update to `dpg-d84t75d7vvec73fhlpfg-a` |
| Startup error mentions retired Postgres | Delete old `DATABASE_URL`; paste new URL; redeploy |
| Host resolves but wrong data | You may still be on old DB — check logs for hostname |
| `.env` on server | Not deployed (gitignored); production never loads `.env` |

Run locally against the new DB (with suffix):

```bash
set APP_ENV=production
set DATABASE_URL=postgresql://...@dpg-d84t75d7vvec73fhlpfg-a/agri_clinic_db
set RENDER_POSTGRES_HOST_SUFFIX=singapore-postgres.render.com
python manage.py verify_production_db
```
