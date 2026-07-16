# Backend completion — operations & observability

## Observability baseline

- `X-Request-ID` via `config.request_id.RequestIdMiddleware` (echoed on responses).
- Structured log events (no tokens/passwords/media URLs):
  - login / refresh rejection / session replacement (mobile auth)
  - `DutyStart` / duty current / `event=duty_manual_completed`
  - `event=duty_auto_expiry_task` / `event=duty_start_route_point` / `event=duty_end_route_point`
  - GPS duplicate / rejection (gps_service)
  - `event=visit_duty_unmatched`
  - day-map legacy fallback metadata
  - `deprecated_endpoint=true` on compatibility wrappers

## Data repair / audit commands (dry-run safe)

```bash
python manage.py repair_duty_consistency --dry-run
python manage.py audit_gps_route_points
python manage.py audit_visit_consistency
python manage.py audit_duty_map_data
python manage.py repair_visit_duty_links
# apply only after review:
python manage.py repair_visit_duty_links --apply
```

## Duty start/end location policy

- **Optional** on start and manual end.
- Valid coords → exactly one permanent `EmployeeRoutePoint` (`start` / `end`) with idempotency keys `duty-start:<id>` / `duty-end:<id>`.
- Invalid/missing coords → duty lifecycle proceeds; no freeze.
- Auto-expiry → **never** invents end GPS.
