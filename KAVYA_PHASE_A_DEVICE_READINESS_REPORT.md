# Kavya Phase A — Device Readiness Report

**Date:** 11 July 2026  
**Repo:** `d:\agri_clinic`  
**Mobile:** `d:\agri_clinic\mobile`  
**Prior commit:** `5839570 fix(mobile): restore authenticated farmer and visit flows`  
**Physical device tests in this session:** **Not performed** (preparation only)

---

## Verdict

**Ready for internal QA**

Code and tooling are prepared for Android smoke testing. A physical-phone pass has **not** been executed in this session, so the product is **not** yet “Ready for limited client QA.”

---

## API configuration found

| Source | Role |
|--------|------|
| `EXPO_PUBLIC_API_BASE` | Primary API root (must include `/api/v1`, no trailing slash) |
| `EXPO_PUBLIC_APP_ENV` | `local` \| `staging` \| `production` |
| `EXPO_PUBLIC_ALLOW_CLEARTEXT` | Opt-in HTTP for local Android only |
| `mobile/lib/config.ts` | Resolves base URL, env, health URL, config warnings |
| `mobile/app.config.js` | Injects `extra` + conditional cleartext via `expo-build-properties` |
| `mobile/app.json` | Static Expo metadata + plugins |
| Default if unset | Android emulator → `http://10.0.2.2:8000/api/v1`; iOS sim → `http://127.0.0.1:8000/api/v1` |

**Health endpoint:** `GET /healthz/` on API origin (not under `/api/v1`).

**No production URL is hardcoded** in mobile source. Local defaults are loopback/emulator only; physical phones must set `EXPO_PUBLIC_API_BASE` to a LAN IP or HTTPS staging host.

Safe template: `mobile/.env.example` (no secrets).

---

## Changes made (this readiness pass)

| Change | Why |
|--------|-----|
| Hardened `mobile/lib/config.ts` | Explicit env, emulator default, config warnings, health URL helper |
| Added `mobile/app.config.js` | Env-aware cleartext **only** when not staging/production |
| Added `mobile/.env.example` | Documented Setup A/B/C values |
| Added `mobile/lib/diagnostics.ts` + Profile **Run API check** | Safe connectivity / auth presence diagnostics |
| `expo-build-properties` | Schema-valid Android `usesCleartextTraffic` |
| Aligned Expo SDK 54 packages | Cleared prior `expo-doctor` dependency drift |
| Softened `config/settings.py` defaults | Removed hardcoded developer LAN IP from defaults |
| Updated `.env.local.example` | Placeholder `YOUR_LAN_IP` for phone testing |
| Updated smoke test + this report | Exact device instructions + evidence table |

---

## Physical-device setup (summary)

### Setup A — Phone + local Django

1. `ipconfig` → LAN IPv4  
2. `.env`: `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` include that IP  
3. `manage.py runserver 0.0.0.0:8000`  
4. Firewall allow TCP 8000  
5. Phone browser: `http://<LAN_IP>:8000/healthz/`  
6. `mobile/.env`: `EXPO_PUBLIC_API_BASE=http://<LAN_IP>:8000/api/v1`  
7. `npx expo start -c` → Profile → Run API check  

### Setup B — Emulator

`EXPO_PUBLIC_API_BASE=http://10.0.2.2:8000/api/v1`

### Setup C — Staging

`EXPO_PUBLIC_APP_ENV=staging` + `https://…/api/v1` + cleartext false  

Full steps: `KAVYA_AGRI_CLINIC_PHASE_A_SMOKE_TEST.md`

---

## Android requirements (inspected)

| Requirement | Configuration |
|-------------|----------------|
| Internet | Default in Expo / React Native |
| Fine/coarse location (foreground) | `expo-location` plugin + `android.permissions` in `app.config.js` |
| Background location | **Not** requested (Phase A) |
| Cleartext HTTP (local only) | `expo-build-properties` → `usesCleartextTraffic` when `APP_ENV` is not staging/production **and** (flag or `http://` API base) |
| Production cleartext | Forced off for `staging` / `production` / `prod` |

---

## Expo dependency findings

Ran `npx expo install --check` and aligned:

- `@react-native-async-storage/async-storage` → `2.2.0`
- `expo` → `~54.0.35`
- `expo-font` → `~14.0.12`
- `expo-location` → `~19.0.8` (SDK 54 expected; **not** an Expo SDK upgrade)
- `expo-router` → `~6.0.24`
- Added `expo-build-properties`

**After fix:**

| Command | Result |
|---------|--------|
| `npx tsc --noEmit` | **Pass** (exit 0) |
| `npx expo-doctor` | **18/18 passed** |
| `npx expo install --check` | **Dependencies are up to date** |

Expo SDK was **not** upgraded beyond the installed SDK 54 line.

---

## Backend configuration findings

| Setting | Local device testing | Production-like |
|---------|----------------------|-----------------|
| `ALLOWED_HOSTS` | Must include LAN IP (via `.env`) | Deploy hostnames only |
| `CSRF_TRUSTED_ORIGINS` | Include `http://<LAN_IP>:8000` if using cookie/CSRF surfaces | HTTPS origins |
| CORS | `CORS_ALLOW_ALL_ORIGINS=true` OK for local; mobile JWT does not rely on CORS | Restrict origins |
| Auth | Mobile JWT + `X-Device-Session` (Phase A) | Unchanged |
| Health | `/healthz/` public | Same |
| Bind | `runserver 0.0.0.0:8000` for LAN | Gunicorn / reverse proxy |

Defaults in `config/settings.py` no longer embed a specific developer IP (`192.168.29.18` removed from defaults).

---

## Remaining blockers (before limited client QA)

1. **Physical Android smoke not yet executed** — fill evidence table in smoke doc.  
2. Tester must set a real LAN IP / staging URL in `mobile/.env` (not committed).  
3. Windows firewall / same-Wi-Fi mistakes remain the most common first failure.  
4. Offline queue still absent (expected for Phase A).  
5. Admin SPA still external — visit visibility in admin is a separate check.  
6. Tokens remain in AsyncStorage (SecureStore is P1, not this pass).

---

## Exact next manual test steps

1. Complete **Setup A** (or B for emulator-only).  
2. Profile → **Run API check** → confirm reachable + environment.  
3. Execute authentication + farmer + visit rows in `KAVYA_AGRI_CLINIC_PHASE_A_SMOKE_TEST.md` evidence table.  
4. Optionally repeat on **Setup C** staging HTTPS.  
5. Only after a filled Pass table on a real phone: consider upgrading verdict to **Ready for limited client QA**.

---

## Updated readiness verdict

**Ready for internal QA**

(Unchanged from Phase A code-complete state; device prep is done, device evidence is still pending.)
