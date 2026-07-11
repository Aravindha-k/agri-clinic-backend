# Kavya Agri Clinic — Phase A Smoke Test (Android)

**Purpose:** Verify P0 mobile integration fixes on a real device or emulator against a running backend.

**App version under test:** mobile `1.0.0` (post Phase A)

**Backend required:** Django API with `/api/v1/mobile/*` reachable from the device (`EXPO_PUBLIC_API_BASE`).

**Lifecycle note:** Visits are **one-shot submit** (create = completed field record). There is no assign → start → complete flow in Phase A.

---

## Setup

1. Start backend (local or staging).
2. Set `EXPO_PUBLIC_API_BASE` to `http://<reachable-host>:8000/api/v1` (not `127.0.0.1` on a physical phone unless using a tunnel/USB reverse).
3. `cd mobile && npx expo start`
4. Open on Android device/emulator.
5. Use a known **FieldAgent** employee ID + password (not a staff admin account).

---

## Authentication

| # | Step | Expected |
|---|------|----------|
| A1 | Fresh install (or clear app storage) → open app | Login screen |
| A2 | Login with valid employee credentials | Lands on Home; no “another device” error |
| A3 | Kill app and reopen | Stays signed in; Home loads KPIs |
| A4 | While logged in, inspect network (optional: Charles/mitm) | Authenticated calls include `Authorization: Bearer …` **and** `X-Device-Session: <uuid>` |
| A5 | Profile → Sign out | Returns to login; tokens + device session cleared |
| A6 | Login as employee B after A logged out | Home for B; no leftover A data on Farmers/Visits |
| A7 | Login as A on device 1, then login as A on device 2 | Device 1 next API call → friendly session message and login screen (HTTP 409 handled) |
| A8 | After long idle / invalidate refresh (if feasible) | Prompted to sign in again; no crash loop |
| A9 | Login success, then enable airplane mode and pull Home | Clear network error / retry; no crash |

**Fail if:** Home immediately shows “logged out because this account was used on another device” after a single-device login.

---

## Farmer flow

| # | Step | Expected |
|---|------|----------|
| F1 | Open Farmers tab | List loads with names/phones (not permanently empty) |
| F2 | Pull to refresh | Reloads without crash |
| F3 | Search by name or phone → Go | Filtered results |
| F4 | Search nonsense | Empty state with retry |
| F5 | Airplane mode → refresh | Error state + Retry |
| F6 | Tap a farmer row | Detail opens for **that farmer ID** (correct name/phone) |
| F7 | New visit → Load farmers → select by name | Selected farmer ID used on submit (not list index) |
| F8 | (If many farmers) Page 1 only is OK in Phase A | No duplicate keys / crash; `keyExtractor` uses `id` |

---

## Visit flow

| # | Step | Expected |
|---|------|----------|
| V1 | Home or Visits → New visit | Wizard opens |
| V2 | Select farmer → optional field → crop + notes → Review | Steps advance; Submit enabled |
| V3 | Grant location permission → Submit | Visit saved; navigate to Visits list; new visit visible |
| V4 | Deny location permission → Submit | Alert with settings option; visit **not** submitted; button re-enables |
| V5 | Disable device location services → Submit | Clear “location services off” message; no crash |
| V6 | Double-tap Submit quickly | Only one successful create (button disabled/loading while busy) |
| V7 | Submit with crop missing | Blocked with crop required message |
| V8 | Force backend validation error (e.g. offline mid-submit) | User-friendly error; form state preserved where possible |
| V9 | After successful submit, open visit from history | Detail shows farmer / crop / notes / GPS captured |
| V10 | Kill app after submit → reopen → Visits | Visit still listed from server |

---

## Workday / tracking (smoke)

| # | Step | Expected |
|---|------|----------|
| W1 | Home → Start Day (with GPS) | Workday started; no unhandled error |
| W2 | Tracking tab | Shows day in progress; last sync may update over time |
| W3 | Stop day | Returns to off the clock |

---

## Pass / fail

- **Phase A pass:** A1–A6, A9, F1–F7, V1–V4, V6, V9–V10 succeed.
- **Record separately:** A7 (multi-device), GPS deny matrix, workday.
- Attach approximate time, API base URL, employee ID (not password), and app build notes.

---

## Known Phase A limitations (not failures)

- No offline visit queue
- No visit photo upload in wizard
- No follow-up scheduling UI
- No push notifications
- Visit lifecycle is one-shot submit only
- Admin SPA is outside this repository — confirm visit visibility in admin separately if available
