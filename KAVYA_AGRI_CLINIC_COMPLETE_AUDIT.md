# Kavya Agri Clinic — Complete Functional, Technical & Product Audit

**Audit date:** 11 July 2026  
**Repository:** `d:\agri_clinic`  
**Scope:** Backend (Django), mobile app (`mobile/`), admin API contract. Admin SPA is **not in this repository**.  
**Method:** Code tracing (UI → API → models), TypeScript compile check, docs cross-check. No runtime E2E against production was executed in this phase.  
**Code changes:** None (audit-only phase).

---

## 1. Executive summary

**Status: Not ready for client testing**

The backend is comparatively mature: JWT auth, farmer/visit/tracking models, admin REST APIs, GPS/duty sessions, offline-oriented visit (`local_sync_id`) and GPS bulk endpoints, audit logs, and optional S3. The Expo mobile client has a coherent screen structure (Home, Tracking, Visits, Farmers, Profile, visit create/detail, farmer detail) but **critical integration defects block the primary field journey**.

### Why this status

| Blocker | Evidence |
|---------|----------|
| Mobile cannot call protected mobile APIs after login | Backend requires `X-Device-Session`; app never stores or sends it (`mobile/context/AuthContext.tsx`, `mobile/lib/api.ts` vs `mobile_api/device_session.py`) |
| Visit create fails at compile/runtime | `captureSilentLocation` used but not imported in `mobile/app/visit/create.tsx:100` (`npm run typecheck` fails) |
| Farmer list shows empty on success | `fetchFarmersPage` does not unwrap `{ success, data: { results } }` (`mobile/lib/api.ts:301–308` vs `utils/pagination.py`) |
| Offline field capture not implemented on mobile | Backend has bulk/sync; mobile has only AsyncStorage for tokens/workday timestamps |
| Admin UI not auditable from this repo | SPA lives at `https://agri-clinic-frontend.onrender.com` (external); only Django `/admin/` + REST APIs are here |

**Honest overall readiness:** backend ≈ ready for **internal API QA**; mobile ≈ **blocked** until P0 integration fixes; full product ≈ **not ready for client testing**.

---

## 2. Architecture overview

### 2.1 High-level diagram

```
┌──────────────────────┐     JWT + REST      ┌─────────────────────────────┐
│  Mobile (Expo RN)    │ ──────────────────► │  Django 5.2 + DRF           │
│  mobile/             │   /api/v1/mobile/*  │  config/ + apps             │
│  AuthContext + fetch │   /api/v1/farmers/* │                             │
│  AsyncStorage tokens │   /api/v1/visits/*  │  PostgreSQL (prod)          │
│  expo-location       │   /api/v1/tracking/*│  Redis + Celery (optional)  │
└──────────────────────┘                     │  Media: local or AWS S3     │
                                             │  Render / Docker / EC2      │
┌──────────────────────┐     JWT + REST      │                             │
│  Admin SPA (external)│ ──────────────────► │  api/admin/, dashboard/,    │
│  Vite @ :5173 /      │   /api/v1/auth/*    │  tracking admin, reports,   │
│  agri-clinic-        │   /api/v1/admin/*   │  masters, notifications,    │
│  frontend.onrender   │                     │  audit_logs, system_settings│
└──────────────────────┘                     └─────────────────────────────┘
         │
         └── Django built-in /admin/ (staff UI, separate from SPA)
```

### 2.2 Technology summary

| Layer | Stack | Root path |
|-------|--------|-----------|
| Mobile | Expo ~54, RN 0.81, TypeScript, expo-router, Context API, AsyncStorage, expo-location | `mobile/` |
| Backend | Django 5.2, DRF, SimpleJWT, Celery/Redis optional, WhiteNoise, django-storages/S3 | repo root |
| Admin UI | **Not in repo** (Vite SPA referenced in CORS/settings) | external |
| Database | PostgreSQL (prod/Render); SQLite fallback locally | `DATABASE_URL` / `db.sqlite3` |
| Offline storage (mobile) | Tokens + workday timestamps only — **no offline visit/farmer queue** | `mobile/lib/authStorage.ts` |
| GPS | Foreground `expo-location`; 30‑min ping while workday active | `mobile/lib/geo.ts`, `hooks/useWorkdayLocationSync.ts` |
| Notifications | Server in-app notifications for staff/employees; **no mobile push (FCM/APNs)** | `notifications/` |
| AWS | Optional S3 media (`USE_S3`); EC2 env template; no SES/SNS in code | `config/settings.py`, `.env.production.example` |
| Deploy | Render (`render.yaml`), Docker Compose, Gunicorn | root |

### 2.3 State management & API layer

- **Mobile state:** `AuthContext` + per-screen `useState`; masters cached in `hooks/useMasters.ts`.
- **API layer:** single `fetch` wrapper `mobile/lib/api.ts` (`apiRequest`, `unwrapData`, auto-refresh on 401).
- **Auth storage:** JWT access/refresh in AsyncStorage (`agri_access`, `agri_refresh`) — not SecureStore.
- **Backend auth:** Admin `POST /api/v1/auth/login/`; mobile `POST /api/v1/mobile/auth/login/` returns `device_session_id` (currently discarded by app).

### 2.4 Key config files

| File | Purpose |
|------|---------|
| `config/settings.py` | Django, JWT, CORS, S3, Redis, Celery |
| `config/urls.py` | All HTTP mounts |
| `.env.local.example` / `.env.production.example` | Env templates |
| `render.yaml`, `Dockerfile`, `docker-compose.yml` | Deploy |
| `mobile/lib/config.ts` | API base URL, GPS interval, workday auto-stop |
| `mobile/app.json` | Expo + location permissions |

---

## 3. Complete feature inventory

| Module | Feature | Mobile | Admin | Backend | Status | Notes |
|--------|---------|--------|-------|---------|--------|-------|
| Auth | Employee login | Yes | — | Yes | **Broken** | Login works; session header not persisted → subsequent mobile APIs 409 |
| Auth | Admin login | — | External | Yes | Partial* | Backend + lockout/IP/timeout OK; SPA not in repo |
| Auth | Token refresh | Yes | External | Yes | Partial | Mobile refreshes; clears tokens on fail; no forced nav to login |
| Auth | Device single-session | No | — | Yes | **Broken** | Backend enforces; mobile ignores `device_session_id` |
| Auth | Logout | Partial | Yes | Yes | Partial | Mobile clears tokens; no redirect to login |
| Home | Dashboard KPIs | Yes | Yes | Yes | **Broken** (mobile) | `/mobile/dashboard/` needs device session |
| Home | Workday start quick | Yes | — | Yes | **Broken** | Same session + error handling gaps |
| Farmers | List / search | Yes | Yes | Yes | **Broken** (mobile) | Envelope unwrap missing; list empty on 200 |
| Farmers | Detail by ID | Yes | Yes | Yes | Partial | Detail uses `unwrapData`; works if JWT-only path succeeds |
| Farmers | Create | Yes | Yes | Yes | Partial | Quick-add wired; blocked if session/list broken |
| Farmers | Edit / photo | Limited | Yes | Yes | Partial | Mobile photo/edit APIs underused |
| Farmers | Duplicate phone | Yes | Yes | Partial | Partial | Serializer uniqueness; **no DB unique** on `phone` |
| Farms / fields | Multi-field | Limited | Read-only admin VS | Yes | Partial | Models exist; mobile wizard barely uses fields |
| Visits | One-shot create | Yes | Create API | Yes | **Broken** | Missing import + device session |
| Visits | List | Yes | Yes | Yes | **Broken** (mobile) | Device session |
| Visits | Detail | Yes | Yes | Yes | Partial | Uses `/visits/{id}/` (no device session); may work with JWT alone |
| Visits | Start / complete lifecycle | API stub | — | Yes | **Not used** | Mobile uses one-shot submit; `completeVisit` unused in UI |
| Visits | Media / images | No UI | Attachments | Yes | Missing (mobile) | Backend media endpoints exist; no ImagePicker in app |
| Visits | Recommendations / advice | Display only | Yes | Yes | Partial | Detail shows advice fields; create wizard only notes/pest/disease |
| Follow-ups | Create / list / overdue | No | No dedicated | Fields only | **Missing** | `follow_up_required`, `next_visit_date` on Visit; dashboard explicitly excludes follow-ups |
| GPS / workday | Start/stop day | Yes | Live map APIs | Yes | **Broken** (mobile) | Session header |
| GPS | Route / map on phone | No map UI | GeoJSON admin | Yes | Partial | Mobile shows sync metadata only; no route map |
| GPS | Offline GPS queue | No | — | Yes bulk | Missing (mobile) | Failed pings dropped |
| Offline sync | Visits / farmers / images | No | — | Yes (`local_sync_id`, bulk) | **Missing** (mobile) | Online-first only |
| Notifications | In-app list | No | API | Yes | Not used (mobile) | No push SDK |
| Notifications | Deep link / reminders | No | — | Partial | Missing | |
| Profile | Me / status | Yes | Employees | Yes | **Broken** | `/mobile/auth/me/` requires device session |
| Profile | Password change | No | Yes | Yes | Missing (mobile) | |
| Profile | Diagnostics / sync counts | No | — | Partial | Missing | `pending_sync` always 0 from dashboard metrics |
| Masters | Districts / villages / crops | Yes | Yes | Yes | Partial | Crop list may mishandle paginated/wrapped responses |
| Products | Catalogue / Rx products | No | No | No | **Missing** | Free-text fertilizer/pesticide only |
| Reports | Field reports | Limited API | Yes | Yes | Partial | Mobile `reports` endpoint unused in UI |
| Territory | Beat / assignment | — | Employee district | Partial | Partial | Farmer `assigned_employee`; no beat plan UI |
| CRM module | Alternate Farmer/Visit | — | — | Orphan | **Not used** | `crm/` not installed/mounted |
| Audit logs | Trail | — | API | Yes | Complete (backend) | |
| System settings | GPS thresholds | — | API | Yes | Partial | Response shape inconsistent (raw array) |
| Import / export | Excel | — | Problem items import | Partial | Partial | Farmer import via management commands; no HTTP export |

\*Admin SPA cannot be confirmed Complete/Broken from this repo alone.

---

## 4. End-to-end flow audit

### 4.1 Authentication (mobile)

| Step | Expected | Actual | Verdict |
|------|----------|--------|---------|
| Login with employee_id | Tokens + user | Works; also returns `device_session_id` | Partial |
| Persist session header | Send `X-Device-Session` | **Not stored/sent** | **Broken** |
| Home / work / visits / me | 200 | **409 SESSION_REPLACED** | **Broken** |
| Token refresh on 401 | New access | Implemented | Complete |
| Refresh fail | Logout + login screen | Tokens cleared; **no redirect** | Partial |
| Sign out | Clear + login | Clear only; stays on Profile | Partial |
| Invalid credentials | Error message | Backend raises auth errors | Complete (backend) |
| Staff login on mobile | Rejected | Correctly rejected | Complete |
| Inactive employee | Rejected | Correctly rejected | Complete |

### 4.2 Home dashboard

Intended: greeting, workday card, today stats, quick actions.

| Data | Source | Correct? |
|------|--------|----------|
| today_visits | `/mobile/visits/stats/` + dashboard | Blocked by 409 |
| completed | stats / dashboard (`completed_visits` = total submitted) | Naming misleading even when fixed |
| pending | Always 0 in `mobile_dashboard_metrics` | Placeholder |
| pending sync | Always 0 | Placeholder (no offline queue) |
| active_visit | Always null | Matches simplified one-shot model |

### 4.3 Farmer management

| Flow | Verdict |
|------|---------|
| List by ID navigation | Farmer detail route `farmer/[id]` — good (ID-based) |
| List population | **Broken** — unwrap gap |
| Search | Wired to query param; ineffective while unwrap broken |
| Pagination | Page 1 only on list screens; unwrap broken |
| Create | Serializer requires name+phone; duplicate phone validated in serializer |
| Multi-farm / crops / consent / language | Models partially support land/irrigation/soil; **UI missing** most of these |
| Farmer visits/activity tabs | Same pagination unwrap bug as list |

### 4.4 Visit lifecycle (intended 20 steps vs product)

Product reality: **one-shot visit submit** (create = complete), not assign → start → arrive → complete.

| Intended step | Status |
|---------------|--------|
| Visit assigned to officer | **Missing** — no assignment queue; employee creates visits |
| Display assigned visits | N/A / list own submitted visits |
| GPS permission | Implemented in `geo.ts` |
| Travel to farmer | Tracking is workday GPS, not visit navigation |
| Visit start | Backend `/visits/start/` exists; **mobile unused** |
| Arrival GPS | Captured at submit time only |
| Farmer / crop / notes / pest / disease | Wizard steps exist |
| Images | **Missing** on mobile |
| Recommendation / products | **Missing** on create (advice fields on model/detail only) |
| Follow-up date | **Missing** on create UI |
| Complete + completion GPS | Folded into create; `completeVisit` unused |
| Offline save | **Missing** |
| History | List API exists; blocked by session |
| Admin visibility | Backend admin visit list exists |
| Reports updated | Backend reports exist |

**Create path today:** missing import → ReferenceError; if fixed → 409 device session.

### 4.5 Follow-up workflow

**Not implemented as a product flow.** Fields exist on `Visit`; mobile dashboard docs say follow-ups are out of active workflow. No list, reminders, overdue, reschedule, or cancel APIs.

### 4.6 GPS and travel tracking

| Area | Finding |
|------|---------|
| Permission | Foreground only; denied cached; settings deep-link helper |
| Background location | **Not implemented** |
| Interval | 30 minutes — coarse for route quality / compliance |
| Failed ping | Swallowed; **no retry queue** |
| Map clutter | Mobile has **no map**; admin GeoJSON should prefer meaningful stops — verify in SPA (not in repo) |
| Mock GPS | `LocationLog.is_suspicious` exists server-side; mobile does not detect mock locations |
| App kill | Interval stops; no background task |
| Auto-stop | Server/client aware of ~9h (`WORKDAY_AUTO_STOP_HOURS`) |

### 4.7 Offline functionality

| Scenario | Result |
|----------|--------|
| No internet before login | Login fails (expected) |
| Internet lost after login | Screens fail; **no local queue** |
| Offline farmer/visit/image/follow-up | **Cannot** |
| Backend bulk sync / `local_sync_id` | Ready; **unused by app** |
| Silent data loss | GPS pings and failed creates are not queued — risk of **lost field evidence** if user believes offline works |

### 4.8 Notifications

In-app backend types: `GPS_OFF`, `OFFLINE`, `ONLINE`, `VISIT_CREATED`, `VISIT_BLOCKED`. Mobile does not poll or register for push. No deep linking.

### 4.9 Admin panel (API-level)

Backend supports: dashboard KPIs, employees, farmers, visits, issues, recommendations, crops/problem catalog, live tracking/routes, reports, notifications, audit logs, system settings, problem-item import.

**Cannot confirm** SPA wiring, mock widgets, or UI-only permissions without the frontend repository. Documented API mismatches (stats key names, pagination shapes, Postman role values) create high risk of “screen looks done but data wrong.”

### 4.10 Roles

| Role | Where defined | Login | Access |
|------|---------------|-------|--------|
| FieldAgent | `EmployeeProfile.ROLE_CHOICES` | Mobile | Own farmers/visits (scoping varies by endpoint) |
| Supervisor | Same | Mobile | **Mostly same as FieldAgent** — not treated as privileged in `visits/access.is_privileged_user` |
| Staff / Admin | `User.is_staff` | `/api/v1/auth/login/` | Admin APIs |
| Superuser | Django | Admin | Full |
| Elevated strings `admin/manager/owner` | Checked in `is_privileged_user` | — | **Not in ROLE_CHOICES** — dead path unless raw DB values |
| Farmer | Data entity only | No login | — |
| Distributor / Agronomist | — | — | **Not in system** |

**UI-only ACL:** cannot verify on admin SPA. Mobile has no role-based screen gating beyond “has token.” Backend generally enforces `IsAuthenticated` / `IsEmployeeUser` / `IsAdminUser` — good. Gap: device session is enforced only on `mobile_api` mixins, not on `/api/v1/farmers/` or `/api/v1/visits/{id}/`, so ACL is **inconsistent across surfaces**.

---

## 5. Critical issues

### C1 — Device session not wired (blocks almost all mobile APIs)

| | |
|--|--|
| **Severity** | P0 — Critical |
| **Files** | `mobile/context/AuthContext.tsx` (`signIn`); `mobile/lib/api.ts` (`apiRequest`); `mobile/lib/authStorage.ts`; `mobile_api/auth.py` (returns `device_session_id`); `mobile_api/device_session.py` |
| **Root cause** | Login returns `device_session_id`; app never persists or attaches `X-Device-Session` |
| **Impact** | After login, dashboard, work, visits, tracking, profile → 409 “logged out on another device” |
| **Fix** | Persist session id; set header on every mobile API call; clear on 409 and redirect to login |

### C2 — Visit create ReferenceError

| | |
|--|--|
| **Severity** | P0 — Critical |
| **Files** | `mobile/app/visit/create.tsx:100`; export exists in `mobile/lib/geo.ts` (`captureSilentLocation`) |
| **Root cause** | Wrong/missing import (`captureLocation` imported, `captureSilentLocation` called) |
| **Impact** | Crash when submitting a visit |
| **Fix** | Import `captureSilentLocation` (or call `captureLocation` and handle result) |

### C3 — Farmer pagination envelope not unwrapped

| | |
|--|--|
| **Severity** | P0 — Critical |
| **Files** | `mobile/lib/api.ts` `fetchFarmersPage`, `fetchFarmerVisitsPage`, `fetchFarmerActivityPage`; backend `utils/pagination.py`, `farmers/views.py` |
| **Root cause** | Response is `{ success, data: { count, results } }`; client reads top-level `results` |
| **Impact** | Empty farmer lists / history with no error |
| **Fix** | `unwrapData` then read `results` |

### C4 — No offline capture despite field operations reality

| | |
|--|--|
| **Severity** | P0 — Data loss risk (product) |
| **Files** | Mobile: no queue; Backend: `Visit.local_sync_id`, `POST /visits/bulk/`, tracking bulk APIs |
| **Root cause** | Online-first client; backend sync features unused |
| **Impact** | Visits/GPS lost when network drops; false confidence if UI implies resilience |
| **Fix** | Minimum: clear UX that online is required; Better: local queue + `local_sync_id` + retry |

### C5 — JWT in AsyncStorage

| | |
|--|--|
| **Severity** | P1 — Security |
| **Files** | `mobile/lib/authStorage.ts` |
| **Root cause** | Tokens not in SecureStore/Keychain |
| **Impact** | Easier token theft on rooted/jailbroken or malware scenarios |
| **Fix** | Move tokens to `expo-secure-store` |

### C6 — Sign-out / 401 / 409 leave user in authenticated shell

| | |
|--|--|
| **Severity** | P1 |
| **Files** | `mobile/app/(tabs)/profile.tsx`; `mobile/app/index.tsx` (only entry redirect); `mobile/lib/api.ts` |
| **Root cause** | No global auth guard; signOut does not `router.replace('/login')` |
| **Impact** | Confusing empty/loading states; stale UI |
| **Fix** | Auth gate in root layout; redirect on signOut and session conflicts |

### C7 — Phone uniqueness not enforced at DB

| | |
|--|--|
| **Severity** | P1 — Data integrity |
| **Files** | `masters/models.py` (`phone` blank, not unique); `farmers/serializers.py` `validate_phone` |
| **Root cause** | App-level only |
| **Impact** | Race/import paths can create duplicate phones |
| **Fix** | Conditional unique constraint (non-empty phones) + cleanup |

### C8 — Inconsistent API surfaces / duplicate mounts

| | |
|--|--|
| **Severity** | P1 — Maintainability / wrong-client risk |
| **Files** | `config/urls.py` (admin mounted at `/api/v1/` and `/api/v1/admin/`); farmers + visits duplicate list; WorkDay vs DutySession vs WorkLog |
| **Impact** | Frontends hit wrong path/shape; harder QA |
| **Fix** | Document canonical paths; deprecate duplicates gradually |

### C9 — Admin SPA not in monorepo

| | |
|--|--|
| **Severity** | P1 — Process / release risk |
| **Impact** | Cannot guarantee admin screens match backend contracts before client demo |
| **Fix** | Bring SPA into monorepo or always audit both repos together |

### C10 — Visit detail may mis-parse / incomplete UX

| | |
|--|--|
| **Severity** | P2 |
| **Files** | `fetchVisitDetail` expects raw object (matches `VisitDetailUpdateAPI` raw `Response`); no complete/media/follow-up actions |
| **Impact** | Read-mostly; notes patch errors swallowed |

### C11 — `print` in visit detail error path

| | |
|--|--|
| **Severity** | P2 |
| **Files** | `visits/api_visit_update.py` ~L121 `print("ERROR:", e)` |
| **Impact** | Sensitive error text may hit logs/stdout |

### C12 — Example DB password in production env template

| | |
|--|--|
| **Severity** | P2 — Ops hygiene |
| **Files** | `.env.production.example` contains sample password `kavyaagri` |
| **Impact** | Weak defaults if copied literally |

---

## 6. Missing validations and edge cases

| Case | Current behavior | Gap |
|------|------------------|-----|
| Same farmer twice | Possible if name differs / phone empty | Need stronger duplicate detection UX |
| Same mobile, two farmers | Blocked in create serializer; not DB-unique | Race + imports |
| Wrong territory | Soft assignment only | No hard territory ACL on farmer list for all endpoints |
| Visit deleted while offline | N/A (no offline) | When offline added: need tombstones |
| Dual-device visit complete | Device session intends single device; mobile ignores it | Dual device possible via JWT-only endpoints |
| Image OK / visit fail | N/A (no images) | When added: transactional or compensating delete |
| Follow-up create fail after visit | N/A | When added: outbox pattern |
| Invalid GPS | Utils validation on some paths | Mobile should reject 0,0 / poor accuracy before submit |
| Wrong device clock | Uses client `visit_date` from ISO today | Prefer server date or skew check |
| Disabled user offline | N/A | On sync: revoke + clear queue |
| Double-tap submit | `busy` flag on create — good | Ensure all mutating buttons disable |
| Masters crop list envelope | `fetchCropsCatalog` assumes array | May break if paginated wrapper |
| Supervisor privileges | Role unused for visit scope | Clarify product intent |

---

## 7. API integration gaps

| Gap | Mobile / Admin | Backend |
|-----|----------------|---------|
| `X-Device-Session` | Not sent | Required on `MobileEmployeeAPIView` |
| Login docs omit `device_session_id` | `docs/MOBILE_API_SYNC_LIST.md` | Returned by `MobileTokenObtainPairSerializer` |
| Farmer list unwrap | Missing | Wrapped pagination |
| Visit create | Broken import | Ready (`local_sync_id` optional) |
| Visit media | Not called | `/mobile/visits/<pk>/media/`, attachments |
| `completeVisit` / start | Dead client code | Endpoints exist |
| Follow-up APIs | None | Fields only |
| Product APIs | None | None |
| Notifications | None | `/api/v1/notifications/` |
| Dashboard field names | `today_visits`, `completed` | Also `visits_today`, `completed_visits`, `pending_visits: 0` |
| Admin dashboard stats keys | Docs/Postman may expect `total_farmers` | `DashboardStatsAPI` uses `farmers`, `fields`, `visits`, `issues_open` |
| Postman role `field_officer` | Docs | Model: `FieldAgent` / `Supervisor` |
| CRM URLs | — | Unmounted |
| `/api/mobile` stub | — | Unmounted; superseded by `mobile_api` |
| System settings GET | Expects envelope | May return raw array |

**Unused backend capabilities (mobile):** bulk visit upload, bulk GPS, visit attachments, map visits, visit-form-options, reports, problem catalog on create, follow-up fields, device session binding.

**Used by mobile but fragile:** `/mobile/*` (session), `/farmers/` (envelope), `/visits/{id}/` (raw detail), `/masters/*` (shape varies).

---

## 8. Missing use cases (classified)

### Must have before client release

- Working login → home → farmers → create visit → visit list (fix C1–C3)
- Explicit online-required messaging **or** minimal offline visit queue
- GPS permission UX that does not crash submit
- Sign-out / session-replaced → login
- Admin SPA smoke test against live APIs (separate repo)

### Important for version 1.1

- Visit photos with retry
- Follow-up date on visit + overdue list (admin + mobile)
- Problem category / master selection on visit (already in masters)
- Stronger farmer duplicate detection + DB unique phone
- Secure token storage
- Password change on mobile
- Export (Excel) for visits/farmers
- Align Supervisor privileges with product rules
- Reduce GPS interval or add meaningful route points for admin maps
- Device session fully enforced or consciously relaxed on all employee APIs

### Useful for future version

- Multi-farm / crop season history UI
- Product catalogue + sample/demo tracking
- Beat plan / daily route plan
- Push notifications + WhatsApp/SMS advisories
- Weather / pest outbreak broadcasts
- Mock-location detection UX
- Group meetings / demos / campaigns
- Geo-fenced farm boundaries
- Agronomist escalation workflow

### Not required for this app (now)

- Full e-commerce ordering
- Distributor portal
- Farmer self-service login app
- Heavy ML photo diagnosis (unless client funded)
- Rewriting to offline-first architecture in one leap (prefer incremental queue)

---

## 9. Release priority

### P0 — Must fix before client testing

1. Persist and send `X-Device-Session`
2. Fix `captureSilentLocation` import / visit submit
3. Unwrap farmer (and related) paginated responses
4. Auth redirect on logout / 409 / failed refresh
5. Smoke-test happy path on a real device against staging API
6. Confirm admin SPA points at same staging API and dashboard keys

### P1 — Must fix before production

1. Offline strategy (queue or honest UX) using `local_sync_id`
2. Visit photos
3. SecureStore for tokens
4. Phone unique constraint + duplicate audit
5. Follow-up fields on create + admin overdue filter
6. Canonical API documentation cleanup
7. Error handling on `startDayQuick` and silent catch blocks
8. Production env hardening (secrets, S3, HTTPS, rate limits review)
9. TypeScript clean (`geo.ts` PermissionStatus typing)

### P2 — Version 1.1

1. Problem catalog on visit form  
2. Reports in mobile / richer admin exports  
3. Map on tracking or visit detail  
4. Supervisor vs FieldAgent ACL  
5. Notification center (poll)  
6. Reduce tracking dead code / unify duty vs workday  

### P3 — Future

Product catalogue, push, SMS/WhatsApp, beat plans, campaigns, farmer app, advanced advisory.

---

## 10. Recommended implementation sequence

1. **Unblock session** — storage + header + 409 handling (no schema change).  
2. **Fix farmer unwrap + visit GPS import** — unlock list/create.  
3. **Auth navigation guard** — prevent ghost sessions.  
4. **Manual smoke on Android** — login → start day → create visit → list → detail → admin sees visit.  
5. **Stabilize API contracts** — update `MOBILE_API_SYNC_LIST.md` with `device_session_id` and pagination.  
6. **Photos + follow-up fields** — extend create wizard; use existing media endpoints.  
7. **Minimal offline outbox** for visits (UUID `local_sync_id`) then GPS bulk.  
8. **Security/hygiene** — SecureStore, phone unique, remove debug prints.  
9. **Admin SPA joint audit** — fix key mismatches.  
10. **Only then** territory/product/push features.

Avoid: rewriting navigation, merging all visit APIs, or building a second CRM while P0 is open.

---

## 11. Test checklist

### Android mobile

- [ ] Login valid / invalid / inactive / staff rejected  
- [ ] Cold start with saved token  
- [ ] Second device login replaces first (409 + message)  
- [ ] Home stats match server for today  
- [ ] Start day / stop day / 9h auto-end  
- [ ] GPS deny / services off / timeout messaging  
- [ ] Farmers list, search, open by ID  
- [ ] Quick-create farmer; duplicate phone error  
- [ ] Create visit with crop + GPS; appears in list  
- [ ] Visit detail shows farmer/crop/notes  
- [ ] Airplane mode: no silent success; clear error  
- [ ] Sign out returns to login  
- [ ] App background/foreground during workday ping  

### Web admin (with SPA repo)

- [ ] Login lockout / timeout  
- [ ] Dashboard numbers vs DB  
- [ ] Employee CRUD + reset password  
- [ ] Farmer CRUD; visit list shows mobile-created visit  
- [ ] Live map / route for employee day  
- [ ] Reports date filters  
- [ ] Notifications mark read  
- [ ] Audit log entry on admin login  

### Backend API

- [ ] OpenAPI `/api/docs/` matches canonical paths  
- [ ] Mobile login returns `device_session_id`  
- [ ] Mobile APIs reject missing session  
- [ ] `local_sync_id` idempotent create  
- [ ] Bulk GPS upload  
- [ ] Healthz with DB down → 503  
- [ ] Media upload size/type limits  

### Offline (once implemented)

- [ ] Queue survives app kill  
- [ ] Partial sync / validation failure / token expiry  
- [ ] No duplicate visits  

### GPS

- [ ] Accuracy recorded  
- [ ] Suspicious/mock handling if enabled  
- [ ] Admin route uses filtered points  

### Notifications

- [ ] Create on GPS_OFF events  
- [ ] Unread count  
- [ ] (Future) push delivery  

### AWS / deploy

- [ ] `USE_S3` media URL reachable  
- [ ] Migrations on deploy  
- [ ] CORS only trusted origins  
- [ ] `DEBUG=False`, secret rotation  

---

## 12. Final recommendation

**Implement now (before any client testing):**

1. Device session end-to-end on mobile  
2. Visit create GPS import fix  
3. Farmer list/detail pagination unwrap  
4. Auth redirects for logout/session conflict  
5. Device smoke test + admin confirmation that visits appear  

**Postpone:**

- Product catalogue, push notifications, beat plans, WhatsApp, farmer self-service, ML diagnosis, full offline-first rewrite, CRM revival, Supervisor micro-roles — until the core visit journey is stable.

**Do not** treat UI presence as completion: Home, Farmers, Visits, Tracking, and Profile are present but currently **not functionally connected** for a field officer under production device-session rules.

**Admin:** treat the external Vite app as a required second audit target before declaring “ready for limited client QA.”

---

## Appendix A — Mobile screen map

| Route | File | Primary APIs |
|-------|------|--------------|
| `/login` | `mobile/app/login.tsx` | `POST /mobile/auth/login/` |
| `/(tabs)` Home | `mobile/app/(tabs)/index.tsx` | dashboard, visit stats, work status, me |
| Tracking | `mobile/app/(tabs)/tracking.tsx` | work status/start/stop, tracking ping |
| Visits | `mobile/app/(tabs)/visits.tsx` | `GET /mobile/visits/` |
| Farmers | `mobile/app/(tabs)/farmers.tsx` | `GET /farmers/` |
| Profile | `mobile/app/(tabs)/profile.tsx` | `GET /mobile/auth/me/` |
| Create visit | `mobile/app/visit/create.tsx` | `POST /mobile/visits/`, farmers, masters |
| Visit detail | `mobile/app/visit/[id].tsx` | `GET/PATCH /visits/{id}/` |
| Farmer detail | `mobile/app/farmer/[id].tsx` | `GET /farmers/{id}/`, visits, activity |

## Appendix B — Backend apps (installed)

`accounts`, `tracking`, `visits`, `notifications`, `masters`, `farmers` (API layer), `audit_logs`, `system_settings`, `reports`, `mobile_api` (+ `api.admin` package, `dashboard` views).

## Appendix C — Confirmation limits

- Admin SPA behavior, mock widgets, and UI-only permissions: **not confirmed** (code absent).  
- Production AWS runtime (S3 on/off, Redis): **environment-dependent**.  
- Exact admin map rendering / point clutter: **not confirmed** without SPA + live GPS data.  
- Full E2E on device against staging: **recommended as next step after P0 fixes**, not executed in this audit phase.
