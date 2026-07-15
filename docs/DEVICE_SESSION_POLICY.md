# Device-session enforcement policy

**Date:** 11 July 2026  
**Header:** `X-Device-Session`  
**Implementation:** `mobile_api/device_session.py` (`DeviceSessionRequiredMixin`)

---

## Policy summary

| Client | Device session required? |
|--------|--------------------------|
| Field employee mobile APIs under `/api/v1/mobile/` | **Yes** |
| Duty / workday / location write APIs used by mobile | **Yes** (existing) |
| Legacy `/api/v1/visits/` list+create (employees) | **Yes** (Phase 1) |
| Legacy `/api/v1/farmers/` list+create (employees) | **Yes** (Phase 1) |
| Admin (`is_staff`) on any of the above | **Exempt** |
| Public auth endpoints (login) | **Exempt** |
| Mobile token refresh | **Requires** valid device session (header, body, or JWT claim) |
| Mobile logout | **Exempt** (revokes device session; JWT-only) |
| Web logout | **Exempt** (does not clear device session) |
| Admin-only `/api/v1/admin/*`, `/api/v1/dashboard/*`, tracking `admin/*` | **Exempt** (JWT + `IsAdminUser`) |
| Masters reference reads (non-mobile mount) | **Intentionally exempt** (shared reference data) |
| All employee **write** surfaces used by mobile (visits update/bulk/media, farmers update/fields/crops/photo, WorkLog start/end, notifications mark-read, change-password, profile photo) | **Required** |

---

## Classification of remaining routes

Reads under legacy `/api/v1/visits/*` and `/api/v1/farmers/*` beyond mixin-covered views may still be JWT-only. Prefer `/api/v1/mobile/*` for field clients. Employee **writes** on those surfaces require `X-Device-Session`.

---

## Rejection cases (employee)

| Case | Expected |
|------|----------|
| Missing `X-Device-Session` | 409 `SESSION_REPLACED` / session required |
| Invalid / revoked session | 409 |
| Session for another user | 409 |
| Revoked session on mobile refresh | 409 `SESSION_REPLACED` |
| `can_login=false` or inactive employee | 403 permission denied |
| Mobile logout | Blacklists refresh + deactivates device sessions; **does not** end DutySession |

Admin JWTs must continue to work without the device header. Web login does **not** replace or clear `EmployeeDeviceSession`.
