# DutySession 9-hour timer and auto-expiry (Phase 3)

## Policy

- Maximum duty length: **9 hours** (`duration_limit_seconds = 32400`).
- `expected_end_at = start_time + 9 hours` (UTC-aware timestamps in DB).
- `start_time` is never modified after create.
- When the deadline is reached, the backend auto-completes the duty:
  - `ended_at` / `end_time` = `expected_end_at` (not job wall-clock time)
  - `auto_ended = True`
  - `completion_reason = AUTO_EXPIRED`
  - public `duty_status` / timer `status` = `AUTO_COMPLETED`
- Elapsed/remaining seconds use **integer floor** of `total_seconds()` (non-negative).

Django: `TIME_ZONE = Asia/Kolkata`, `USE_TZ = True`. Business dates use `timezone.localdate()`.

## Canonical modules

| Concern | Module |
|--------|--------|
| Timer math + response fields | `tracking/duty_timer.py` |
| Auto-completion (idempotent) | `tracking/duty_expiry.py` |
| Start/end/current payload | `tracking/duty_service.py` (`serialize_duty_status`) |
| Celery task | `tracking/tasks.expire_overdue_duties_task` |
| Management fallback | `python manage.py expire_overdue_duties` |

## Lazy expiry (no app required)

Applied before returning / creating duties on:

- `GET /api/tracking/duty/current/`
- `POST /api/tracking/duty/start/`
- Compatibility current/status paths via `serialize_duty_status` / `expire_overlong_workdays_for_user`
- Location updates via active-duty fetch

**Behaviour when overdue:** finalize first; `current` returns the completed timer state. Start does not auto-create a new duty after expiry — client must start explicitly after business-date rules allow.

## Scheduled expiry (production)

Code configures Celery Beat:

```
expire-overdue-duties-every-5-minutes → tracking.tasks.expire_overdue_duties_task
CELERY_TIMEZONE = Asia/Kolkata
```

**Code present ≠ production operational.** Production needs both:

```bash
celery -A config worker -l info
celery -A config beat -l info
```

Without beat (or cron calling `expire_overdue_duties`), only **lazy expiry** on authenticated API hits will close overdue duties. Logout / offline / closed app do not affect server-side deadline calculation, but a dormant server with no beat and no API traffic will leave rows active until the next lazy/Celery/management run.

## Manual end

- Before deadline: `ended_at = server now`, `completion_reason = MANUAL`.
- At/after deadline: auto-expiry wins; manual end does not overwrite `ended_at`.
- Repeated end is idempotent.

## Compatibility

WorkDay is synced only through the duty expiry/end paths. WorkLog must not own timer state.
