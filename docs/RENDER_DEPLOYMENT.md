# Render Deployment Setup

## Service model

This repo uses a Render Blueprint file at [render.yaml](../render.yaml).

- Web service: `agri-clinic-backend`
- Runtime: Python
- Build: `pip install -r requirements.txt`
- Pre-deploy: migrations + collectstatic
- Start: `gunicorn config.wsgi:application`
- Health check: `/healthz/`

## Database wiring

`DATABASE_URL` is sourced from Blueprint `fromDatabase.connectionString`.
This avoids manual hostname mistakes.

## Required env vars in Render

Set on the web service:

- `SECRET_KEY` (manual secret)
- `DEBUG=False`
- `ALLOWED_HOSTS=agri-clinic-backend.onrender.com`
- `APP_ENV=production`
- `CORS_ALLOW_ALL_ORIGINS=false`
- `CORS_ALLOWED_ORIGINS=https://agri-clinic-frontend.onrender.com`
- `CSRF_TRUSTED_ORIGINS=https://agri-clinic-backend.onrender.com`

## Deploy flow

1. Push code to `main`.
2. In Render, sync Blueprint and deploy.
3. Confirm service health endpoint returns HTTP 200 at `/healthz/`.
4. Confirm migrations ran successfully from deploy logs.

## Troubleshooting

If deploy fails during migrations with DB connection errors:

- Verify Blueprint database name references the intended Render DB.
- Re-sync Blueprint so `DATABASE_URL` is refreshed from `fromDatabase`.
- Do not manually paste partial hostnames into `DATABASE_URL`.
