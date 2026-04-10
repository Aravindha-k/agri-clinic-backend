#!/usr/bin/env python3
"""
AgriField Mobile API Smoke Test
================================
Tests all API endpoints consumed by the React Native mobile application.

Usage:
    python mobile_api_smoke_test.py
    python mobile_api_smoke_test.py --base-url http://192.168.29.18:8000/api/v1
    python mobile_api_smoke_test.py --employee-id EMP001 --password secret123

Requirements:
    pip install requests
"""

import argparse
import json
import sys
from typing import Optional

import requests

# ── Configuration ──────────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_EMPLOYEE_ID = "EMP001"
DEFAULT_PASSWORD = "password"
TIMEOUT = 10  # seconds

# ── Colour helpers (ANSI) ──────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}✔{RESET}  {msg}")


def fail(msg):
    print(f"  {RED}✘{RESET}  {msg}")


def warn(msg):
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def info(msg):
    print(f"  {CYAN}→{RESET}  {msg}")


# ── Result tracking ────────────────────────────────────────────────────────────
results = []  # list of (feature, endpoint, status, note)


def record(feature: str, endpoint: str, passed: bool, note: str = ""):
    results.append((feature, endpoint, "PASS" if passed else "FAIL", note))


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def get(session: requests.Session, url: str, **kwargs):
    try:
        r = session.get(url, timeout=TIMEOUT, **kwargs)
        return r
    except requests.RequestException as e:
        return _fake_error(str(e))


def post(session: requests.Session, url: str, **kwargs):
    try:
        r = session.post(url, timeout=TIMEOUT, **kwargs)
        return r
    except requests.RequestException as e:
        return _fake_error(str(e))


class _fake_error:
    """Mimics a response object for network-level errors."""

    def __init__(self, msg):
        self.status_code = 0
        self._msg = msg
        self.text = msg

    def json(self):
        return {"error": self._msg}


def _pretty(r) -> str:
    try:
        body = r.json()
        text = json.dumps(body, indent=2)
        if len(text) > 400:
            text = text[:400] + "\n  ... (truncated)"
        return text
    except Exception:
        return r.text[:300] if r.text else "(empty body)"


def _check(r, expected_codes=(200, 201), label="") -> bool:
    passed = r.status_code in expected_codes
    status_str = f"HTTP {r.status_code}"
    if passed:
        ok(f"{label}  [{status_str}]")
    else:
        fail(f"{label}  [{status_str}]")
        print(f"     Response: {_pretty(r)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — AUTH
# ══════════════════════════════════════════════════════════════════════════════
def test_auth(
    session: requests.Session, base: str, employee_id: str, password: str
) -> Optional[str]:
    print(f"\n{BOLD}{CYAN}STEP 1 — Authentication{RESET}")

    # 1a. Login
    endpoint = "/mobile/auth/login/"
    info(f"POST {endpoint}")
    r = post(
        session,
        base + endpoint,
        json={"employee_id": employee_id, "password": password},
    )
    passed = _check(r, (200,), "Login")
    record("Login", endpoint, passed)

    if not passed:
        fail("Cannot continue without a valid token.")
        return None

    body = r.json()
    access = body.get("access") or body.get("access_token")
    refresh = body.get("refresh") or body.get("refresh_token")

    if not access:
        fail(f"No access token in response. Keys: {list(body.keys())}")
        record("Login token", endpoint, False, "Missing access token in response")
        return None

    ok(f"Access token received (length={len(access)})")
    ok(f"Refresh token received: {'yes' if refresh else 'NO'}")

    # Attach Bearer token to session
    session.headers.update({"Authorization": f"Bearer {access}"})

    # 1b. Get me
    endpoint = "/mobile/auth/me/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Get current user (me)")
    record("Get Me", endpoint, passed, body.get("employee_id", ""))
    if passed:
        u = r.json()
        info(
            f"Logged in as: {u.get('first_name', '')} {u.get('last_name', '')} [{u.get('employee_id', '?')}]"
        )

    # 1c. Refresh token (if we have one)
    if refresh:
        endpoint = "/mobile/auth/refresh/"
        info(f"POST {endpoint}")
        tmp = (
            requests.Session()
        )  # use a clean session so we don't clobber the main token
        r2 = post(tmp, base + endpoint, json={"refresh": refresh})
        passed2 = _check(r2, (200,), "Refresh access token")
        record("Token Refresh", endpoint, passed2)
    else:
        warn("Skipping token refresh — no refresh token in login response")
        record(
            "Token Refresh", "/mobile/auth/refresh/", False, "No refresh token returned"
        )

    return access


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
def test_dashboard(session: requests.Session, base: str):
    print(f"\n{BOLD}{CYAN}STEP 2 — Dashboard{RESET}")
    endpoint = "/mobile/dashboard/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Dashboard summary")
    record("Dashboard", endpoint, passed)

    if passed:
        body = r.json()
        keys = list(body.keys())
        info(f"Response keys: {keys}")
        for field in (
            "today_visits",
            "completed_visits",
            "pending_visits",
            "total_farmers",
        ):
            if field in body:
                ok(f"Field '{field}' = {body[field]}")
            else:
                warn(f"Field '{field}' missing (may be named differently)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — WORKDAY
# ══════════════════════════════════════════════════════════════════════════════
def test_workday(session: requests.Session, base: str):
    print(f"\n{BOLD}{CYAN}STEP 3 — Workday{RESET}")

    # 3a. Work status
    endpoint = "/mobile/work/status/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Get work status")
    record("Work Status", endpoint, passed)
    if passed:
        body = r.json()
        status = body.get("work_status") or body.get("status") or "unknown"
        info(f"Current work status: {status}")

    # 3b. Start work (only if not already started)
    endpoint = "/mobile/work/start/"
    info(f"POST {endpoint}")
    r = post(session, base + endpoint)
    passed = _check(
        r, (200, 201, 400), "Start workday"
    )  # 400 = already started = acceptable
    record(
        "Start Work", endpoint, r.status_code in (200, 201)
    )  # 400 is not a pass for the record
    if r.status_code == 400:
        warn(f"400 response (likely already started): {_pretty(r)}")

    # 3c. Stop work
    endpoint = "/mobile/work/stop/"
    info(f"POST {endpoint}")
    r = post(session, base + endpoint)
    passed = _check(r, (200, 201, 400), "Stop workday")
    record("Stop Work", endpoint, r.status_code in (200, 201))
    if r.status_code == 400:
        warn(f"400 response (likely not started): {_pretty(r)}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — VISITS
# ══════════════════════════════════════════════════════════════════════════════
def test_visits(session: requests.Session, base: str) -> Optional[int]:
    print(f"\n{BOLD}{CYAN}STEP 4 — Visits{RESET}")
    visit_id = None

    # 4a. List visits
    endpoint = "/visits/list/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "List visits")
    record("Visits List", endpoint, passed)
    if passed:
        body = r.json()
        visits = body.get("results") or (body if isinstance(body, list) else [])
        info(f"Total visits returned: {len(visits)}")
        if visits:
            visit_id = visits[0].get("id")
            info(
                f"First visit id={visit_id}, status={visits[0].get('status')}, farmer={visits[0].get('farmer_name')}"
            )

    # 4b. Today's visits
    endpoint = "/visits/list/?today=true"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Today's visits")
    record("Visits Today", "/visits/list/", passed)

    # 4c. Active visit
    endpoint = "/visits/active/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200, 204, 404), "Active visit")
    record("Active Visit", endpoint, r.status_code in (200, 204, 404))
    if r.status_code == 200:
        body = r.json()
        info(f"Active visit: id={body.get('id')}, farmer={body.get('farmer_name')}")
    else:
        info("No active visit (expected if none in progress)")

    return visit_id


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — FARMERS
# ══════════════════════════════════════════════════════════════════════════════
def test_farmers(session: requests.Session, base: str) -> Optional[int]:
    print(f"\n{BOLD}{CYAN}STEP 5 — Farmers{RESET}")
    farmer_id = None

    # 5a. List farmers
    endpoint = "/farmers/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "List farmers")
    record("Farmers List", endpoint, passed)
    if passed:
        body = r.json()
        farmers = body.get("results") or (body if isinstance(body, list) else [])
        info(f"Total farmers: {len(farmers)}")
        if farmers:
            farmer_id = farmers[0].get("id")
            info(
                f"First farmer id={farmer_id}, name={farmers[0].get('name')}, village={farmers[0].get('village')}"
            )

    # 5b. Farmer detail
    if farmer_id:
        endpoint = f"/farmers/{farmer_id}/"
        info(f"GET {endpoint}")
        r = get(session, base + endpoint)
        passed = _check(r, (200,), f"Farmer detail (id={farmer_id})")
        record("Farmer Detail", f"/farmers/{{id}}/", passed)

    return farmer_id


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — TRACKING / MAP
# ══════════════════════════════════════════════════════════════════════════════
def test_tracking(session: requests.Session, base: str):
    print(f"\n{BOLD}{CYAN}STEP 6 — Map / GPS Tracking{RESET}")

    # 6a. Map farmers
    endpoint = "/map/farmers/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Map farmers (with coordinates)")
    record("Map Farmers", endpoint, passed)
    if passed:
        body = r.json()
        farmers = body.get("results") or (body if isinstance(body, list) else [])
        info(f"Farmers with GPS coords: {len(farmers)}")

    # 6b. Push location
    endpoint = "/tracking/location/push/"
    info(f"POST {endpoint}")
    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "accuracy": 5.0,
        "timestamp": "2026-03-11T10:00:00Z",
    }
    r = post(session, base + endpoint, json=payload)
    passed = _check(r, (200, 201), "GPS location push")
    record("GPS Push", endpoint, passed)

    # 6c. Bulk location
    endpoint = "/tracking/location/bulk/"
    info(f"POST {endpoint}")
    payload = {
        "locations": [
            {
                "latitude": 12.9716,
                "longitude": 77.5946,
                "timestamp": "2026-03-11T10:00:00Z",
            },
            {
                "latitude": 12.9725,
                "longitude": 77.5941,
                "timestamp": "2026-03-11T10:00:30Z",
            },
        ]
    }
    r = post(session, base + endpoint, json=payload)
    passed = _check(r, (200, 201), "GPS bulk push")
    record("GPS Bulk Push", endpoint, passed)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — REPORTS
# ══════════════════════════════════════════════════════════════════════════════
def test_reports(session: requests.Session, base: str):
    print(f"\n{BOLD}{CYAN}STEP 7 — Reports{RESET}")
    endpoint = "/mobile/reports/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Reports summary")
    record("Reports", endpoint, passed)
    if passed:
        body = r.json()
        info(f"Response keys: {list(body.keys())}")
        for field in (
            "visits_today",
            "total_visits",
            "completed_visits",
            "pending_visits",
            "total_farmers",
        ):
            val = body.get(field)
            if val is not None:
                ok(f"  {field} = {val}")
            else:
                warn(f"  '{field}' not present")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════
def test_notifications(session: requests.Session, base: str):
    print(f"\n{BOLD}{CYAN}STEP 8 — Notifications{RESET}")
    endpoint = "/notifications/list/"
    info(f"GET {endpoint}")
    r = get(session, base + endpoint)
    passed = _check(r, (200,), "Notifications list")
    record("Notifications", endpoint, passed)
    if passed:
        body = r.json()
        items = body.get("results") or (body if isinstance(body, list) else [])
        info(f"Total notifications: {len(items)}")
        unread = sum(1 for n in items if not n.get("is_read", True))
        info(f"Unread: {unread}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — START VISIT + COMPLETE (integration flow)
# ══════════════════════════════════════════════════════════════════════════════
def test_visit_flow(session: requests.Session, base: str, farmer_id: Optional[int]):
    print(f"\n{BOLD}{CYAN}STEP 9 — Visit Create → Complete Flow{RESET}")
    if not farmer_id:
        warn("Skipping visit flow — no farmer_id available")
        record("Visit Start", "/visits/start/", False, "No farmer_id to test with")
        return

    # Start visit
    endpoint = "/visits/start/"
    info(f"POST {endpoint}  (farmer_id={farmer_id})")
    r = post(session, base + endpoint, json={"farmer_id": farmer_id})
    passed = _check(r, (200, 201), "Start visit")
    record("Visit Start", endpoint, passed)

    if not passed:
        return

    visit_id = r.json().get("id")
    info(f"New visit id={visit_id}")

    if not visit_id:
        warn("No visit id in response — cannot test complete")
        return

    # Complete visit
    endpoint = f"/visits/{visit_id}/complete/"
    info(f"POST {endpoint}")
    r = post(session, base + endpoint, json={})
    passed = _check(r, (200, 201), "Complete visit")
    record("Visit Complete", f"/visits/{{id}}/complete/", passed)


# ══════════════════════════════════════════════════════════════════════════════
# FINAL REPORT TABLE
# ══════════════════════════════════════════════════════════════════════════════
def print_report():
    print(f"\n{'═' * 80}")
    print(f"{BOLD}  FINAL AUDIT REPORT{RESET}")
    print(f"{'═' * 80}")

    col_w = [26, 34, 8]
    header = (
        f"  {'Feature':<{col_w[0]}} {'Endpoint':<{col_w[1]}} {'Status':<{col_w[2]}}"
    )
    print(f"{BOLD}{header}{RESET}")
    print(f"  {'-' * (sum(col_w) + 4)}")

    passed = 0
    failed = 0
    for feature, endpoint, status, note in results:
        color = GREEN if status == "PASS" else RED
        note_str = f"  ({note})" if note else ""
        print(
            f"  {feature:<{col_w[0]}} {endpoint:<{col_w[1]}} {color}{status}{RESET}{note_str}"
        )
        if status == "PASS":
            passed += 1
        else:
            failed += 1

    print(
        f"\n  Total: {passed + failed}  •  {GREEN}{passed} PASS{RESET}  •  {RED}{failed} FAIL{RESET}"
    )
    print(f"{'═' * 80}\n")

    if failed > 0:
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="AgriField Mobile API Smoke Test")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help="API base URL (no trailing slash)"
    )
    parser.add_argument(
        "--employee-id", default=DEFAULT_EMPLOYEE_ID, help="Employee ID for login"
    )
    parser.add_argument(
        "--password", default=DEFAULT_PASSWORD, help="Password for login"
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    print(f"\n{BOLD}AgriField Mobile API Smoke Test{RESET}")
    print(f"Base URL : {base}")
    print(f"Employee : {args.employee_id}")
    print(f"{'─' * 60}")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    # Run all steps
    access_token = test_auth(session, base, args.employee_id, args.password)
    if not access_token:
        print_report()
        return

    test_dashboard(session, base)
    test_workday(session, base)
    farmer_id = test_farmers(session, base)
    visit_id = test_visits(session, base)
    test_tracking(session, base)
    test_reports(session, base)
    test_notifications(session, base)
    test_visit_flow(session, base, farmer_id)

    print_report()


if __name__ == "__main__":
    main()
