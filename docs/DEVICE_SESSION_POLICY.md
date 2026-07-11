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
| Public auth endpoints (login/refresh) | **Exempt** |
| Admin-only `/api/v1/admin/*`, `/api/v1/dashboard/*`, tracking `admin/*` | **Exempt** (JWT + `IsAdminUser`) |
| Masters read (any authenticated) | **Intentionally exempt** (shared reference data) |
| Token refresh | **Exempt** from device session; **checks** `can_login` / active on mobile refresh |

---

## Classification of remaining legacy routes

Routes under `/api/v1/visits/*` and `/api/v1/farmers/*` beyond list/create may still be JWT-only. Treat them as **legacy / migrate-to-mobile** — prefer `/api/v1/mobile/*` for field clients. Closing every legacy view is a follow-up; Phase 1 closed the highest-risk write/list bypasses for visits and farmers.

---

## Rejection cases (employee)

| Case | Expected |
|------|----------|
| Missing `X-Device-Session` | 409 `SESSION_REPLACED` / session required |
| Invalid / revoked session | 409 |
| Session for another user | 409 |
| `can_login=false` or inactive employee | 403 permission denied |

Admin JWTs must continue to work without the device header.
