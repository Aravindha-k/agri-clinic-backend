# Kavya Agri Clinic — Implementation Plan

**Companion to:** `KAVYA_AGRI_CLINIC_COMPLETE_AUDIT.md`  
**Date:** 11 July 2026  
**Rule:** Do not start implementation until stakeholders accept this backlog priority. Prefer small, testable PRs that restore the field journey before adding features.

---

## Guiding principles

1. Fix integration blockers before new product features.  
2. Prefer using existing backend capabilities (`X-Device-Session`, `local_sync_id`, media endpoints) over new architecture.  
3. Do not remove working APIs; deprecate duplicates via docs first.  
4. Admin SPA lives outside this repo — schedule joint fixes with that codebase.  
5. Every P0/P1 task needs a manual test on Android + API check.

---

## Backlog

| Priority | Module | Task | Files affected | Backend change | Mobile change | Admin change | Test required | Risk |
|----------|--------|------|----------------|----------------|---------------|--------------|---------------|------|
| P0 | Auth | Persist `device_session_id` from login; send `X-Device-Session` on all authenticated requests | `mobile/lib/authStorage.ts`, `mobile/lib/api.ts`, `mobile/context/AuthContext.tsx` | No (already returns session) | Yes | No | Login → home 200; second device → 409 | Low |
| P0 | Auth | On 409 `SESSION_REPLACED` / failed refresh: clear tokens + navigate to login | `mobile/lib/api.ts`, `mobile/app/_layout.tsx` or auth gate | No | Yes | No | Dual login UX | Low |
| P0 | Auth | Sign-out redirects to `/login`; root layout guards tabs when `!token` | `mobile/app/(tabs)/profile.tsx`, `mobile/app/_layout.tsx`, `mobile/app/index.tsx` | No | Yes | No | Sign out / deep link without token | Low |
| P0 | Visits | Fix `captureSilentLocation` import (or use `captureLocation`) in create wizard | `mobile/app/visit/create.tsx` | No | Yes | No | `npm run typecheck`; submit visit | Low |
| P0 | Farmers | Unwrap paginated envelope in `fetchFarmersPage`, `fetchFarmerVisitsPage`, `fetchFarmerActivityPage` | `mobile/lib/api.ts` | No | Yes | No | Farmers list populated; farmer history tabs | Low |
| P0 | Masters | Harden `fetchDistricts` / `fetchVillages` / `fetchCropsCatalog` for wrapped/paginated responses | `mobile/lib/api.ts`, `mobile/hooks/useMasters.ts` | No | Yes | No | Crop picker non-empty | Low |
| P0 | QA | Device smoke: login → start day → create visit → list → detail; admin sees visit | Staging env + admin SPA | No | Verify | Verify | Full happy path checklist | Med |
| P0 | Docs | Document `device_session_id` + header + pagination envelope in API sync list | `docs/MOBILE_API_SYNC_LIST.md`, Postman collections | Docs only | No | No | Client engineers can integrate | Low |
| P1 | UX | Surface errors on Home `startDayQuick` (Alert / ErrorState); disable double-tap | `mobile/app/(tabs)/index.tsx` | No | Yes | No | Start day failure paths | Low |
| P1 | GPS | Fix `PermissionStatus` typing in `geo.ts` (use enum, not string literals) | `mobile/lib/geo.ts` | No | Yes | No | `npm run typecheck` clean | Low |
| P1 | Security | Store JWT in SecureStore instead of AsyncStorage | `mobile/lib/authStorage.ts`, `package.json` | No | Yes | No | Login persists across restart | Med |
| P1 | Offline | Add local visit outbox (UUID `local_sync_id`) + sync on reconnect; show pending count | New: `mobile/lib/offlineQueue.ts` (or similar); `mobile/lib/api.ts`; Home pending UI | Prefer existing `POST /mobile/visits/` + `local_sync_id` | Yes | Optional pending health | Offline create → online sync; no duplicates | High |
| P1 | Offline | Queue failed GPS pings; flush via bulk location API | `useWorkdayLocationSync.ts`, `api.ts` | Use existing bulk endpoints | Yes | No | Airplane mode then sync | Med |
| P1 | Offline | Honest banner when offline and queue empty (“Online required”) until outbox ships | Home / create screens | No | Yes | No | Airplane mode UX | Low |
| P1 | Visits | Add photo capture + upload on create or detail (`/mobile/visits/{id}/media/` or multipart create) | `create.tsx` or `[id].tsx`, `api.ts`; Expo image picker dep | No if using existing media APIs | Yes | Verify attachments | Photo appears in admin visit | Med |
| P1 | Visits | Add optional follow-up required + next visit date on create; show on detail | `create.tsx`, `api.ts`, serializers already accept fields | Minor validation only if needed | Yes | Add overdue filter on visit list | Follow-up date saved | Med |
| P1 | Farmers | Add DB unique constraint for non-empty `phone`; run duplicate audit command | `masters/models.py`, migration; `farmers/serializers.py` | Yes | No | No | Duplicate phone rejected; migration safe | Med |
| P1 | Auth | Align non-`mobile_api` employee endpoints with session policy (either require header or document JWT-only carve-out) | `farmers/views.py` and/or mixin reuse; docs | Yes | Already sending header after P0 | No | No accidental dual-device write | Med |
| P1 | Profile | Password change screen calling existing change-password API | New screen + `api.ts` | No | Yes | No | Password change + re-login | Low |
| P1 | Admin | Joint audit of SPA: dashboard key names, pagination shapes, role values | External frontend repo + `api/admin/views.py` | Fix mismatches if SPA correct | No | Yes | Dashboard KPIs match DB | Med |
| P1 | Backend | Remove `print` debug in visit detail; use logger | `visits/api_visit_update.py` | Yes | No | No | Error path still 500 envelope | Low |
| P1 | Backend | Normalize system settings response to success envelope | `system_settings/views.py` | Yes | No | Yes if SPA parses raw | Settings screen | Low |
| P1 | Ops | Production checklist: secrets, CORS, `DEBUG`, S3, HTTPS | `.env.production.example`, deploy docs | Config | Config | Config | Deploy smoke | Med |
| P2 | Visits | Wire problem category / problem master on create using visit-form-options | `create.tsx`, `api.ts`; `GET /mobile/visit-form-options/` | No | Yes | No | Problem saved on visit | Med |
| P2 | Visits | Show recommendation / advice fields on create (or agronomist-only on admin) | `create.tsx`, admin recommendation UI | No | Yes | Yes | Advice visible both sides | Low |
| P2 | Follow-up | Dedicated overdue follow-up list API + mobile tab | New view under `visits` or `mobile_api`; list UI | Yes | Yes | Yes | Overdue filter | Med |
| P2 | Tracking | Optional shorter GPS interval or visit-stop markers only for admin map | `mobile/lib/config.ts`; `tracking` filters | Maybe | Yes | Map UX | Battery vs accuracy | Med |
| P2 | Tracking | Detect/mock-location flag surfacing to admin | `tracking` models already have `is_suspicious` | Enhance detection | Optional | Badge on live map | Compliance review | Med |
| P2 | Notifications | Mobile poll unread count + list; deep link to visit if id present | New screens; `notifications` APIs | No | Yes | Existing | Mark read | Med |
| P2 | Reports | Surface daily/monthly mobile reports or share link | `mobile_api/reports.py`, new screen | No | Yes | Export buttons if missing | Numbers match admin | Med |
| P2 | Roles | Define Supervisor privileges (e.g. team visit read) and implement in `visits/access.py` | `accounts/models.py`, `visits/access.py` | Yes | Optional role UI | Yes | Supervisor sees team only | High |
| P2 | API hygiene | Document canonical mounts; mark duplicate `/api/v1/` admin shadow + WorkLog legacy as deprecated | `docs/`, optionally OpenAPI tags | Docs first | No | Update client base paths | Regression if clients on aliases | Med |
| P2 | Farmers | Multi-field create/edit UX; land size / irrigation / soil | Farmer detail + forms | No | Yes | Fields write if needed | Field saved under farmer | Med |
| P2 | Export | Admin HTTP export CSV/Excel for visits and farmers | New `reports` or admin endpoints | Yes | No | Yes | File downloads | Med |
| P2 | Code quality | Extract shared unwrap/pagination helpers; remove unused Expo boilerplate components | `mobile/lib/`, `components/` | No | Yes | No | Typecheck + smoke | Low |
| P2 | Tests | Add mobile integration tests for session header + farmer unwrap; expand backend device-session tests | `mobile` tests; `mobile_api/tests/` | Yes | Yes | No | CI green | Med |
| P3 | Products | Product catalogue model + recommend product on visit | New app/models; serializers; UIs | Yes | Yes | Yes | Product on visit | High |
| P3 | Push | FCM/APNs via expo-notifications; server push provider | New infra | Yes | Yes | Broadcast UI | Push received | High |
| P3 | Comms | SMS / WhatsApp advisory share | Integrations | Yes | Yes | Templates | Opt-in consent | High |
| P3 | Planning | Beat plan / daily route assignment | New models + admin assign + mobile agenda | Yes | Yes | Yes | Assigned visits appear | High |
| P3 | Farmer app | Farmer-facing login (out of scope for field-force MVP) | Separate client | Yes | New app | — | — | High |
| P3 | Cleanup | Remove or install orphan `crm` app; remove unused `api/mobile` stub | `crm/`, `api/mobile/`, `config/` | Yes | No | No | No URL regressions | Med |

---

## Suggested PR sequence (ordered)

### Phase A — Unblock field journey (1–3 days)

1. Device session storage + header + 409 handling  
2. Farmer pagination unwrap + masters response hardening  
3. Visit create GPS import + typecheck green  
4. Auth navigation guard + sign-out redirect  
5. Manual Android smoke + admin visibility check  

**Exit criteria:** Field agent can complete one online visit end-to-end; TypeScript passes.

### Phase B — Production safety (3–7 days)

6. SecureStore tokens  
7. Offline messaging or visit outbox (`local_sync_id`)  
8. Visit photos  
9. Follow-up date on create + admin overdue filter (minimal)  
10. Phone uniqueness migration + duplicate audit  
11. Backend log hygiene + settings envelope  
12. Joint admin SPA contract fixes  

**Exit criteria:** Ready for **limited client QA** on staging.

### Phase C — v1.1 product depth

13. Problem catalog on visit  
14. Notifications poll  
15. Supervisor ACL  
16. Export + richer reports  
17. GPS/map polish  

### Phase D — Future backlog

18. Products, push, beat plans, SMS/WhatsApp — only with explicit client priority.

---

## Task detail — P0 reference

### A1. Device session

**Backend (already done):** `mobile_api/auth.py` returns `device_session_id`; `DeviceSessionRequiredMixin` reads `X-Device-Session`.

**Mobile work:**

1. `authStorage`: save/load/clear `agri_device_session`.  
2. `signIn`: after `mobileLogin`, persist `res.device_session_id`.  
3. `apiRequest`: set header `X-Device-Session` when present.  
4. On 409: `clearTokens` + clear session + notify AuthContext / redirect.

**Test:** First request to `/mobile/dashboard/` returns 200; second phone login invalidates first.

### A2. Farmer unwrap

```ts
// Pattern
const raw = await apiRequest(...);
const data = unwrapData<{ count: number; results: FarmerListItem[] }>(raw);
return data;
```

Apply to farmers list, farmer visits, farmer activity.

### A3. Visit create

Import `captureSilentLocation` from `@/lib/geo` (already exported). Keep `busy` guard.

---

## Dependencies / ownership

| Area | Owner suggestion |
|------|------------------|
| Mobile P0/P1 | Mobile engineer |
| Backend uniqueness / session alignment | Backend engineer |
| Admin SPA key fixes | Frontend (external repo) |
| Staging device QA | QA + field ops sample user |
| Release decision | Product owner after Phase B exit criteria |

---

## Explicitly postponed (do not start in Phase A)

- Full offline-first rewrite (SQLite/Watermelon)  
- Product catalogue  
- Push notifications  
- Rewriting tracking (DutySession vs WorkDay merge) in one PR  
- Farmer self-service app  
- Large admin UI redesign  

---

## Definition of done (release gates)

| Gate | Status target from audit |
|------|--------------------------|
| After Phase A | **Ready for internal QA** |
| After Phase B | **Ready for limited client QA** |
| After Phase C + ops hardening + monitoring | Consider **Ready for production** |

Current repo state (pre-implementation): **Not ready for client testing** — see audit executive summary.
