# Canonical Mobile & Web API Contract (Backend Completion)

Migration guide for clients switching to canonical DutySession / GPS / Visit / day-map APIs.

## Error envelope

**Success:** `{ "success": true, "message": string, "data": object }`

**Error:** `{ "success": false, "message": string, "errors": object|null, "code": string }`

### Stable error codes

| Code | Meaning |
|------|---------|
| `SESSION_REPLACED` | Device session revoked / replaced (HTTP 409) |
| `ACCOUNT_DISABLED` | Employee inactive |
| `NO_ACTIVE_DUTY` | No active DutySession for write |
| `DUTY_ALREADY_COMPLETED` | Duty already ended (idempotent end may still return 200) |
| `INVALID_COORDINATES` / `INVALID_COORDS` | Bad lat/lng |
| `VALIDATION_ERROR` | Payload validation |
| `DUPLICATE_REPLAY` | Idempotent GPS/visit replay (often returned as success with `duplicate: true`) |
| `RATE_LIMITED` | Throttled |
| `FORBIDDEN` | Ownership / role |
| `NOT_FOUND` | Resource missing or not visible |

Auth for mobile writes: `Authorization: Bearer <access>` + `X-Device-Session: <session_id>`.

---

## Authentication

### POST `/api/v1/mobile/auth/login/`

- Auth: none (throttled)
- Body: `employee_id`, `password`, `device_name`, `platform`, `app_version`
- Response: `access`, `refresh`, `device_session_id`, user profile
- Offline: not applicable
- Compat: web `POST /api/v1/auth/login/` (no device session)

### POST `/api/v1/mobile/auth/refresh/`

- Body: `refresh` (+ device session header)
- Validates active `EmployeeDeviceSession`
- Errors: `SESSION_REPLACED`, `ACCOUNT_DISABLED`

### POST `/api/v1/mobile/auth/logout/`

- Blacklists refresh; deactivates device session

### GET `/api/v1/mobile/auth/me/`

- Profile only

### GET `/api/v1/mobile/bootstrap/` (canonical)

Alias: `GET /api/v1/mobile/auth/bootstrap/`

Response `data`:

```json
{
  "user": { "...profile..." },
  "device_session": { "id": "...", "status": "ACTIVE" },
  "current_duty": null,
  "day_map": null,
  "server_now": "ISO-8601",
  "feature_flags": {
    "canonical_duty": true,
    "canonical_gps": true,
    "canonical_visits": true,
    "canonical_day_map": true,
    "duty_start_end_route_points": true
  },
  "minimum_supported_app_version": null,
  "force_update": false
}
```

- `current_duty`: same payload as `GET /api/v1/tracking/duty/current/`
- `day_map`: **summary only** (counts, bounds, start/end flags, `full_map_path`). Fetch full map separately.
- Location for duty start/end: **optional**. Missing/invalid coords do not fail duty lifecycle.

---

## Duty (canonical)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v1/tracking/duty/start/` | Optional `latitude`/`longitude`. Creates `WORKDAY_START` route point when coords valid. Idempotent restore. Key: `duty-start:<duty_id>` |
| GET | `/api/v1/tracking/duty/current/` | Timer from `duty_timer` only |
| POST | `/api/v1/tracking/duty/end/` | Optional end coords → `WORKDAY_END` (`duty-end:<duty_id>`). Auto-expiry never fabricates GPS |

Device session required for employee mobile clients.

---

## GPS

| Method | Path |
|--------|------|
| POST | `/api/v1/tracking/gps/update/` (and duty location update aliases) |
| POST | `/api/v1/tracking/gps/bulk/` |

- Idempotency: `client_point_id` per duty
- Writer: `tracking.gps_service` only → `EmployeeRoutePoint`
- Offline: queue + replay; duplicates return without second insert

---

## Visits

| Method | Path |
|--------|------|
| POST | `/api/v1/mobile/visits/` or canonical field-visit create |
| POST | bulk / offline sync (mobile) |
| GET/PATCH | detail/update |
| POST | media / attachments |

- Service: `visits.services.field_visit_service`
- Links `duty_session` when unambiguous; else nullable + `event=visit_duty_unmatched`
- Never creates DutySession from a visit

---

## Map

| Method | Path |
|--------|------|
| GET | `/api/v1/tracking/duty/<id>/map/` |
| GET | `/api/v1/tracking/duty/current/map/` |

Builder: `tracking.day_map_service`. Prefers explicit `WORKDAY_START` / `WORKDAY_END` points.

---

## Compatibility → canonical (frozen)

| Legacy | Canonical | Status |
|--------|-----------|--------|
| `POST /api/v1/mobile/work/start/` | `POST /api/v1/tracking/duty/start/` | Deprecated OpenAPI + `deprecated_endpoint` log |
| `POST /api/v1/mobile/work/stop/` | `POST /api/v1/tracking/duty/end/` | Deprecated |
| `GET /api/v1/mobile/work/status/` | `GET /api/v1/tracking/duty/current/` | Deprecated |
| `POST /api/v1/work/start/` | duty start | Deprecated wrapper |
| `POST /api/v1/work/stop/` | duty end | Deprecated wrapper |
| Admin route by date (no DutySession) | `duty/<id>/map/` | Compat empty/legacy note |

**Do not add new business logic to compatibility wrappers.**

---

## Web

Web JWT login may omit device session. Current duty and day-map must still use the same `DutySession` + `day_map_service` / `serialize_duty_status` contracts.
