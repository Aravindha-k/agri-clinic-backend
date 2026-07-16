# Celery / Redis production readiness

## Status legend

| Area | Status |
|------|--------|
| Code (task, beat schedule, idempotent expiry) | **Verified in repo** |
| Settings (broker/backend/timezone) | **Verified in repo** |
| `/readyz/` / `/livez/` / `/healthz/` | **Verified in repo** |
| Render Blueprint celery worker/beat services | **Not configured** (`render.yaml` is web-only) |
| Physical Redis + worker + beat in production | **Not verified** |

**Do not claim production auto-expiry is running until worker and beat are deployed and monitored.**

Lazy expiry on duty current/end still works without Celery.

---

## Configuration (code)

| Setting | Source |
|---------|--------|
| `CELERY_BROKER_URL` | `CELERY_BROKER_URL` or `REDIS_URL` (default `memory://` for local) |
| `CELERY_RESULT_BACKEND` | `CELERY_RESULT_BACKEND` or Redis / `cache+memory://` |
| `CELERY_TIMEZONE` | `Asia/Kolkata` |
| Beat | `expire-overdue-duties-every-5-minutes` → `tracking.tasks.expire_overdue_duties_task` |
| Task | `acks_late`, `max_retries=3`, idempotent `expire_overdue_duties` |
| Ready gate | `CELERY_REQUIRED_FOR_READY=true` makes `/readyz/` fail on memory/missing broker |

---

## Process commands

```bash
celery -A config worker -l info
celery -A config beat -l info
# or combined (dev only):
celery -A config worker -B -l info
```

Manual fallback:

```bash
python manage.py expire_overdue_duties
```

---

## Health endpoints

| Path | Role |
|------|------|
| `/livez/` | Process up |
| `/healthz/` | Liveness + DB |
| `/readyz/` | DB + broker configuration hint |

Celery ping is **not** required for readiness by default (worker may be a separate service).

---

## Deployment checklist (ops)

1. Provision Redis; set `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`.
2. Deploy **worker** and **beat** (or cron calling `expire_overdue_duties`).
3. Confirm beat fires every ~5 minutes; logs contain `event=duty_auto_expiry_task`.
4. Confirm auto-expiry does **not** create fabricated `WORKDAY_END` GPS points.
5. Optionally set `CELERY_REQUIRED_FOR_READY=true` on worker-dependent environments.

## Infrastructure note

`render.yaml` currently defines only the web service. Adding worker/beat is an infrastructure change outside this backend code completion phase.
