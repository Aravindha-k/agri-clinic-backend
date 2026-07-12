# Kavya Agri Clinic — Phase A Smoke Test (Android)

**Purpose:** Verify P0 mobile integration fixes on a real device or emulator against a running backend.

**App version under test:** mobile `1.0.0` (post Phase A + device readiness)

**Backend required:** Django API with `/api/v1/mobile/*` and public `GET /healthz/`.

**Lifecycle note:** Visits are **one-shot submit** (create = completed field record). There is no assign → start → complete flow in Phase A.

**Do not claim physical-device pass** unless tests were run on a physical Android phone.

---

## Quick start (all setups)

1. Backend running and reachable from the test device.
2. Mobile env configured (see setups below) → `cd mobile` → copy `.env.example` to `.env` and edit.
3. `npx expo start -c`
4. Open app (Expo Go or dev client).
5. **Profile → Run API check** before login flows if connectivity is uncertain.
6. Use a **FieldAgent** employee ID + password (not staff admin).

---

## Setup A — Physical Android phone + local backend

### Backend (Windows PC)

1. Find LAN IPv4 (same Wi-Fi as the phone):
   ```powershell
   ipconfig
   ```
   Use the Wireless LAN adapter IPv4 (example: `192.168.1.42`). **Not** `127.0.0.1`.

2. In repo root `.env` (from `.env.local.example`), set:
   ```env
   ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.42
   CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://192.168.1.42:8000
   DEBUG=True
   APP_ENV=local
   CORS_ALLOW_ALL_ORIGINS=true
   ```
   Replace `192.168.1.42` with your real LAN IP. Do not commit this `.env`.

3. Bind Django to all interfaces:
   ```powershell
   cd d:\agri_clinic
   .\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
   ```

4. Firewall: allow inbound TCP **8000** for Private networks (Windows Defender Firewall), or temporarily allow Python.

5. From the phone browser (same Wi-Fi), open:
   ```text
   http://192.168.1.42:8000/healthz/
   ```
   Expect JSON like `{"status":"ok","database":"ok"}`.

### Mobile

1. `cd d:\agri_clinic\mobile`
2. Copy `.env.example` → `.env`:
   ```env
   EXPO_PUBLIC_APP_ENV=local
   EXPO_PUBLIC_API_BASE=http://192.168.1.42:8000/api/v1
   EXPO_PUBLIC_ALLOW_CLEARTEXT=true
   ```
3. Restart Metro with cache clear: `npx expo start -c`
4. Profile → **Run API check** → API reachable should be **Yes**.

**Configured where:** `mobile/.env` → `EXPO_PUBLIC_*`; cleartext via `mobile/app.config.js` + `expo-build-properties` (local/http only).

---

## Setup B — Android emulator + local backend

1. Run Django (localhost is enough for the emulator bridge):
   ```powershell
   .\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
   ```
2. Mobile `.env`:
   ```env
   EXPO_PUBLIC_APP_ENV=local
   EXPO_PUBLIC_API_BASE=http://10.0.2.2:8000/api/v1
   EXPO_PUBLIC_ALLOW_CLEARTEXT=true
   ```
   `10.0.2.2` is the Android emulator alias for the host machine’s loopback.
3. `npx expo start -c` → open Android emulator.
4. Profile → **Run API check**.

---

## Setup C — Physical Android phone + staging backend

1. Staging must expose **HTTPS** (no cleartext).
2. Mobile `.env`:
   ```env
   EXPO_PUBLIC_APP_ENV=staging
   EXPO_PUBLIC_API_BASE=https://YOUR_STAGING_HOST/api/v1
   EXPO_PUBLIC_ALLOW_CLEARTEXT=false
   ```
3. `npx expo start -c` (or your staging EAS profile when available).
4. Profile → **Run API check**:
   - Environment shows `staging`
   - API host shows your HTTPS hostname
   - No HTTP-in-production warning

**Backend staging:** `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` / TLS already set by deploy env — do not weaken production security for this test.

---

## Authentication checklist

| # | Step | Expected |
|---|------|----------|
| A1 | Fresh install (or clear app storage) → open app | Login screen |
| A2 | Login with valid employee credentials | Lands on Home; no “another device” error |
| A3 | Kill app and reopen | Stays signed in; Home loads KPIs |
| A4 | Profile → Run API check after login | Auth restored Yes; device session Present (masked) |
| A5 | Profile → Sign out | Returns to login; tokens + device session cleared |
| A6 | Login as employee B after A logged out | Home for B; no leftover A data |
| A7 | Login as A on device 1, then login as A on device 2 | Device 1 next API → session message + login |
| A8 | Airplane mode after login → pull Home | Clear network error / retry; no crash |

**Fail if:** Home immediately shows session-replaced after a single-device login.

---

## Farmer / visit / workday checklists

(Same expectations as Phase A P0.)

### Farmers

| # | Step | Expected |
|---|------|----------|
| F1 | Farmers tab | List loads |
| F2 | Pull to refresh | Reloads |
| F3 | Search name/phone | Filtered results |
| F4 | Nonsense search | Empty state |
| F5 | Airplane → refresh | Error + Retry |
| F6 | Open farmer by row | Correct ID/detail |
| F7 | New visit → select farmer | ID-based selection |

### Visits

| # | Step | Expected |
|---|------|----------|
| V1 | New visit | Wizard opens |
| V2 | Farmer → field → crop → review | Steps OK |
| V3 | Grant GPS → Submit | Saved; appears in Visits |
| V4 | Deny GPS → Submit | Alert; not submitted; button re-enables |
| V5 | Location services off → Submit | Clear message; no crash |
| V6 | Double-tap Submit | Single create |
| V7 | Open visit from history | Detail correct |
| V8 | Kill app after submit → Visits | Still listed |

### Workday

| # | Step | Expected |
|---|------|----------|
| W1 | Start Day | Starts without crash |
| W2 | Tracking tab | In progress |
| W3 | Stop day | Off the clock |

---

## Smoke-test evidence template

Fill this on the device under test. Leave **Actual** blank until you run the step.

| Test | Expected | Actual | Pass/Fail | Evidence/Notes |
|------|----------|--------|-----------|----------------|
| Fresh login | Home loads; no 409 | | | |
| Device-session accepted | Authenticated APIs succeed; diag shows session Present | | | |
| App restart restores session | Still logged in after kill | | | |
| Farmer list loads | Names/phones visible | | | |
| Farmer search | Filter works | | | |
| Farmer detail opens | Correct farmer by ID | | | |
| Create visit opens | Wizard shown | | | |
| GPS permission accepted | Visit submits with location | | | |
| GPS permission denied | Alert; no visit saved | | | |
| Location services disabled | Clear error; no crash | | | |
| Valid visit submission | Success alert; list refresh | | | |
| Double-tap prevention | One visit only | | | |
| Visit appears in history | Row in Visits tab | | | |
| Logout | Login screen; diag shows tokens Missing | | | |
| Invalid device session | Second device login → first device forced to login | | | |
| Network loss | Error/retry; no crash | | | |
| App relaunch | Restores or login cleanly | | | |
| Diagnostics API check | `/healthz/` reachable Yes | | | |

**Tester:** _______________ **Date:** _______________ **API host:** _______________ **Employee ID:** _______________

---

## Pass / fail gate

- **Internal QA pass:** Setup A or B connectivity OK + A1–A6 + F1–F7 + V1–V4 + V6–V8.
- **Limited client QA:** Same on Setup C (HTTPS staging) with evidence table filled.

---

## Known Phase A limitations (not failures)

- No offline visit queue
- No visit photo upload in wizard
- No follow-up scheduling UI
- No push notifications
- Visit lifecycle is one-shot submit only
- Admin SPA is outside this repository
