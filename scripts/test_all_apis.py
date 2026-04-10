#!/usr/bin/env python
"""
scripts/test_all_apis.py
────────────────────────
End-to-end API smoke-test for Agri Clinic backend.

Usage:
    # From project root with venv active:
    python scripts/test_all_apis.py

    # Override server URL / credentials:
    BASE_URL=http://127.0.0.1:8000/api/v1 ADMIN_USER=admin ADMIN_PASS=admin123 python scripts/test_all_apis.py

Requirements:
    pip install requests
"""

import os
import sys
import json
import time
import uuid
from datetime import date, timedelta
from typing import Optional, Any

import requests

# ──────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000/api/v1")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
REQUEST_TIMEOUT = int(os.getenv("TIMEOUT", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
TODAY = date.today().isoformat()


# ──────────────────────────────────────────────────────────────
# ANSI COLOURS
# ──────────────────────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GREY = "\033[90m"


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def green(s):
    return f"{C.GREEN}{s}{C.RESET}" if _supports_color() else s


def red(s):
    return f"{C.RED}{s}{C.RESET}" if _supports_color() else s


def yellow(s):
    return f"{C.YELLOW}{s}{C.RESET}" if _supports_color() else s


def cyan(s):
    return f"{C.CYAN}{s}{C.RESET}" if _supports_color() else s


def bold(s):
    return f"{C.BOLD}{s}{C.RESET}" if _supports_color() else s


def grey(s):
    return f"{C.GREY}{s}{C.RESET}" if _supports_color() else s


# ──────────────────────────────────────────────────────────────
# RESULT TRACKING
# ──────────────────────────────────────────────────────────────
results: list[dict] = []


def record(name: str, passed: bool, detail: str = ""):
    results.append({"name": name, "passed": passed, "detail": detail})
    icon = green("[PASS]") if passed else red("[FAIL]")
    arrow = f"  {grey('→')} {red(detail)}" if not passed and detail else ""
    print(f"  {icon} {name}{arrow}")


# ──────────────────────────────────────────────────────────────
# HTTP HELPERS
# ──────────────────────────────────────────────────────────────
class Session:
    """Thin wrapper around requests.Session with auth header and retry."""

    def __init__(self):
        self._s = requests.Session()
        self._s.headers.update({"Content-Type": "application/json"})

    def set_token(self, token: str):
        self._s.headers.update({"Authorization": f"Bearer {token}"})

    def clear_token(self):
        self._s.headers.pop("Authorization", None)

    def _request(
        self, method: str, path: str, retries: int = MAX_RETRIES, **kwargs
    ) -> requests.Response:
        url = f"{BASE_URL}{path}"
        attempt = 0
        last_exc = None
        while attempt <= retries:
            try:
                resp = self._s.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
                return resp
            except requests.ConnectionError as exc:
                last_exc = exc
                attempt += 1
                if attempt <= retries:
                    time.sleep(0.5 * attempt)
        raise ConnectionError(
            f"Cannot reach {url} after {retries + 1} attempts. "
            f"Is the Django server running?\n  {last_exc}"
        )

    def get(self, path, **kw):
        return self._request("GET", path, **kw)

    def post(self, path, **kw):
        return self._request("POST", path, **kw)

    def put(self, path, **kw):
        return self._request("PUT", path, **kw)

    def patch(self, path, **kw):
        return self._request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self._request("DELETE", path, **kw)


http = Session()


# ──────────────────────────────────────────────────────────────
# ASSERTION HELPERS
# ──────────────────────────────────────────────────────────────
def check(
    test_name: str,
    resp: requests.Response,
    expected_status: int | tuple[int, ...] = 200,
    require_success_flag: bool = True,
) -> tuple[bool, Any]:
    """
    Validate a response and record pass/fail.

    Returns (passed: bool, body: dict | None)
    """
    if isinstance(expected_status, int):
        expected_status = (expected_status,)

    # Status code check
    if resp.status_code not in expected_status:
        detail = (
            f"HTTP {resp.status_code} (expected {'/'.join(map(str, expected_status))})"
        )
        try:
            err = resp.json()
            msg = (
                err.get("message")
                or err.get("detail")
                or err.get("error", {}).get("message", "")
                or json.dumps(err)[:120]
            )
            if msg:
                detail += f" — {msg}"
        except Exception:
            detail += f" — {resp.text[:120]}"
        record(test_name, False, detail)
        return False, None

    # Parse JSON
    try:
        body = resp.json()
    except Exception:
        record(test_name, False, "Response is not valid JSON")
        return False, None

    # Optional success flag check
    if require_success_flag and isinstance(body, dict) and "success" in body:
        if not body.get("success"):
            msg = body.get("message") or str(body.get("error", ""))
            record(test_name, False, f"success=false — {msg[:120]}")
            return False, body

    record(test_name, True)
    return True, body


def extract(body: Any, *keys) -> Any:
    """Safely dig into a nested dict: extract(body, 'data', 'id')"""
    val = body
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val


# ──────────────────────────────────────────────────────────────
# SECTION HEADER
# ──────────────────────────────────────────────────────────────
def section(title: str):
    width = 60
    bar = "─" * width
    print(f"\n{cyan(bar)}")
    print(f"{bold(cyan(f'  {title}'))}")
    print(f"{cyan(bar)}")


# ──────────────────────────────────────────────────────────────
# STATE  (IDs discovered at runtime)
# ──────────────────────────────────────────────────────────────
state: dict = {
    "admin_token": None,
    "emp_token": None,
    "district_id": None,
    "village_id": None,
    "crop_id": None,
    "farmer_id": None,
    "visit_id": None,
    "employee_id": None,  # DB pk of created user
    "employee_username": None,
    "notification_id": None,
    "workday_active": False,
}

# Unique suffix so re-runs don't collide on unique fields
RUN_ID = uuid.uuid4().hex[:6]


# ══════════════════════════════════════════════════════════════
# TEST SUITES
# ══════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────
# 1. AUTH
# ──────────────────────────────────────────────────────────────
def test_auth():
    section("01 · AUTH")

    # --- Login ---
    resp = http.post(
        "/auth/login/", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    # Login returns raw tokens (no success wrapper)
    passed, body = check(
        "Login (admin)", resp, expected_status=200, require_success_flag=False
    )
    if not passed:
        print(red("\n  ✖  Cannot continue without a valid token. Aborting.\n"))
        sys.exit(1)

    token = body.get("access")
    if not token:
        print(red("  ✖  No 'access' token in login response. Aborting.\n"))
        sys.exit(1)

    state["admin_token"] = token
    http.set_token(token)
    print(grey(f"     token={token[:20]}…"))

    # --- Get profile ---
    resp = http.get("/employees/me/")
    _, body = check("Get My Profile (me)", resp, 200)


# ──────────────────────────────────────────────────────────────
# 2. MASTERS — Districts, Villages, Crops
# ──────────────────────────────────────────────────────────────
def test_masters():
    section("02 · MASTERS  (Districts / Villages / Crops)")

    # --- Create or reuse district ---
    district_name = f"Test District {RUN_ID}"
    resp = http.post("/masters/districts/", json={"name": district_name})
    if resp.status_code == 201:
        record("Create District", True)
        state["district_id"] = resp.json().get("id")
    elif resp.status_code == 400:
        # Name conflict → list and grab first active one
        list_resp = http.get("/masters/districts/")
        _, lbody = check(
            "List Districts (fallback)", list_resp, 200, require_success_flag=False
        )
        results_list = lbody.get("results") if lbody else []
        if results_list:
            state["district_id"] = results_list[0]["id"]
            record("Create District (reused existing)", True)
        else:
            record(
                "Create District",
                False,
                "Duplicate name and no existing district found",
            )
    else:
        check("Create District", resp, 201)

    # --- List districts ---
    resp = http.get("/masters/districts/")
    check("List Districts", resp, 200, require_success_flag=False)

    if not state["district_id"]:
        print(
            yellow(
                "  ⚠  No district_id — skipping village / crop / farmer / visit tests"
            )
        )
        return

    # --- Create or reuse village ---
    village_name = f"Test Village {RUN_ID}"
    resp = http.post(
        "/masters/villages/",
        json={"name": village_name, "district": state["district_id"]},
    )
    if resp.status_code == 201:
        record("Create Village", True)
        state["village_id"] = resp.json().get("id")
    else:
        list_resp = http.get(f"/masters/villages/?search=Test Village")
        _, lbody = check(
            "List Villages (fallback)", list_resp, 200, require_success_flag=False
        )
        results_list = (lbody or {}).get("results", [])
        if results_list:
            state["village_id"] = results_list[0]["id"]
            record("Create Village (reused existing)", True)
        else:
            check("Create Village", resp, 201)

    # --- List villages ---
    resp = http.get(f"/masters/villages/?district={state['district_id']}")
    check("List Villages (by district)", resp, 200, require_success_flag=False)

    # --- Create or reuse crop ---
    resp = http.post(
        "/masters/crops/", json={"name_en": f"Crop {RUN_ID}", "name_ta": "பயிர்"}
    )
    if resp.status_code == 201:
        record("Create Crop", True)
        state["crop_id"] = resp.json().get("id")
    else:
        list_resp = http.get("/masters/crops/")
        _, lbody = check(
            "List Crops (fallback)", list_resp, 200, require_success_flag=False
        )
        results_list = (lbody or {}).get("results", [])
        if results_list:
            state["crop_id"] = results_list[0]["id"]
            record("Create Crop (reused existing)", True)
        else:
            check("Create Crop", resp, 201)

    # --- List crops ---
    resp = http.get("/masters/crops/")
    check("List Crops", resp, 200, require_success_flag=False)


# ──────────────────────────────────────────────────────────────
# 3. EMPLOYEES
# ──────────────────────────────────────────────────────────────
def test_employees():
    section("03 · EMPLOYEES")

    username = f"emp_{RUN_ID}"
    password = "Test@12345"
    phone = f"9{''.join([str(i % 10) for i in range(9)])}"  # 9-digit suffix

    resp = http.post(
        "/employees/create/",
        json={
            "username": username,
            "password": password,
            "phone": phone,
        },
    )
    passed, body = check("Create Employee", resp, (200, 201))
    if passed:
        # ID may be nested in data or at top-level depending on view
        emp_id = (
            extract(body, "data", "id")
            or extract(body, "id")
            or extract(body, "data", "user_id")
        )
        state["employee_id"] = emp_id
        state["employee_username"] = username
        state["employee_password"] = password
        print(grey(f"     employee_id={emp_id}  username={username}"))

    # --- List employees ---
    resp = http.get("/employees/")
    check("List Employees", resp, 200)

    # --- Get my profile ---
    resp = http.get("/employees/me/")
    check("Admin Profile (me)", resp, 200)


# ──────────────────────────────────────────────────────────────
# 4. FARMERS
# ──────────────────────────────────────────────────────────────
def test_farmers():
    section("04 · FARMERS")

    if not state["district_id"] or not state["village_id"]:
        print(yellow("  ⚠  Skipped — no district/village IDs available"))
        return

    phone = f"8{RUN_ID[:9].ljust(9,'0')}"  # unique-ish phone each run

    resp = http.post(
        "/masters/farmers/",
        json={
            "name": f"Farmer {RUN_ID}",
            "phone": phone,
            "district": state["district_id"],
            "village": state["village_id"],
            "total_land_area": "3.50",
        },
    )
    passed, body = check("Create Farmer", resp, (200, 201), require_success_flag=False)
    if passed:
        farmer_id = extract(body, "id")
        state["farmer_id"] = farmer_id
        print(grey(f"     farmer_id={farmer_id}"))

    resp = http.get("/masters/farmers/")
    check("List Farmers (Masters)", resp, 200, require_success_flag=False)

    resp = http.get("/admin/farmers/")
    check("List Farmers (Admin router)", resp, 200, require_success_flag=False)

    if state["farmer_id"]:
        resp = http.get(f"/masters/farmers/{state['farmer_id']}/")
        check("Get Farmer Detail", resp, 200, require_success_flag=False)


# ──────────────────────────────────────────────────────────────
# 5. VISITS
# ──────────────────────────────────────────────────────────────
def test_visits():
    section("05 · VISITS")

    if not state["district_id"] or not state["village_id"]:
        print(yellow("  ⚠  Skipped — no district/village IDs available"))
        return

    payload = {
        "farmer_name": f"Test Farmer {RUN_ID}",
        "farmer_phone": f"7{RUN_ID[:9].ljust(9,'0')}",
        "district": state["district_id"],
        "village": state["village_id"],
        "visit_date": TODAY,
        # Admin can omit lat/lon (is_staff=True skips lat/lon validation)
        "land_name": "Test Plot",
        "land_area": 1.5,
        "season": "kharif",
        "crop_health": "good",
        "notes": f"Automated test visit {RUN_ID}",
        "pest_issue": False,
        "disease_issue": False,
        "follow_up_required": False,
    }
    if state["crop_id"]:
        payload["crop"] = state["crop_id"]
        payload["crop_stage"] = "vegetative"

    resp = http.post("/visits/", json=payload)
    passed, body = check("Create Visit", resp, 201)
    if passed:
        visit_id = extract(body, "data", "visit_id") or extract(body, "data", "id")
        state["visit_id"] = visit_id
        print(grey(f"     visit_id={visit_id}"))

    resp = http.get("/visits/")
    check("List Visits", resp, 200, require_success_flag=False)

    if state["visit_id"]:
        resp = http.get(f"/visits/{state['visit_id']}/")
        check("Get Visit Detail", resp, 200, require_success_flag=False)

        resp = http.patch(
            f"/visits/{state['visit_id']}/", json={"notes": "Updated by test"}
        )
        check("Update Visit (PATCH)", resp, (200, 201), require_success_flag=False)

    resp = http.get("/visits/stats/")
    check("Visit Stats", resp, 200)


# ──────────────────────────────────────────────────────────────
# 6. TRACKING  (must use employee token — admins are blocked)
# ──────────────────────────────────────────────────────────────
def test_tracking():
    section("06 · TRACKING  (employee token)")

    # --- Employee login ---
    if not state.get("employee_username"):
        print(yellow("  ⚠  No employee created — skipping tracking tests"))
        return

    resp = http.post(
        "/auth/login/",
        json={
            "username": state["employee_username"],
            "password": state["employee_password"],
        },
    )
    # Temporarily override auth header; will restore admin token after
    if resp.status_code != 200:
        record("Employee Login (for tracking)", False, f"HTTP {resp.status_code}")
        return

    emp_token = resp.json().get("access")
    if not emp_token:
        record("Employee Login (for tracking)", False, "No access token in response")
        return

    record("Employee Login (for tracking)", True)
    http.set_token(emp_token)
    state["emp_token"] = emp_token

    # --- Start workday ---
    resp = http.post("/tracking/workday/start/", json={})
    if resp.status_code == 400 and "already started" in (resp.text or "").lower():
        record("Start Workday (already active — OK)", True)
        state["workday_active"] = True
    else:
        passed, _ = check("Start Workday", resp, 201, require_success_flag=False)
        state["workday_active"] = passed

    # --- Push location ---
    resp = http.post(
        "/tracking/location/push/",
        json={
            "latitude": 11.9416,
            "longitude": 79.3193,
            "accuracy": 10.0,
            "battery_level": 80,
        },
    )
    check("Push Location", resp, (200, 201), require_success_flag=False)

    # --- Heartbeat ---
    resp = http.post("/tracking/heartbeat/", json={})
    check("Heartbeat", resp, 200, require_success_flag=False)

    # --- Current workday ---
    resp = http.get("/tracking/workday/current/")
    check("Get Current Workday", resp, 200, require_success_flag=False)

    # --- End workday ---
    if state["workday_active"]:
        resp = http.post("/tracking/workday/end/", json={})
        check("End Workday", resp, 200, require_success_flag=False)
        state["workday_active"] = False

    # --- Restore admin token ---
    http.set_token(state["admin_token"])


# ──────────────────────────────────────────────────────────────
# 7. TRACKING ADMIN  (admin token)
# ──────────────────────────────────────────────────────────────
def test_tracking_admin():
    section("07 · TRACKING — ADMIN VIEWS")

    http.set_token(state["admin_token"])

    resp = http.get("/tracking/admin/status/")
    check("Admin — All Employees Status", resp, 200)

    resp = http.get(f"/tracking/admin/dashboard-stats/?date={TODAY}")
    check("Admin — Tracking Dashboard Stats", resp, 200)

    resp = http.get("/tracking/admin/geo/employees/")
    check("Admin — Employee GeoJSON", resp, 200)

    if state["employee_id"]:
        uid = state["employee_id"]
        resp = http.get(f"/tracking/admin/employee/{uid}/summary/?date={TODAY}")
        check(f"Admin — Employee Summary (uid={uid})", resp, 200)

        resp = http.get(f"/tracking/admin/employee/{uid}/route/?date={TODAY}")
        check(f"Admin — Employee Route (uid={uid})", resp, 200)


# ──────────────────────────────────────────────────────────────
# 8. DASHBOARD
# ──────────────────────────────────────────────────────────────
def test_dashboard():
    section("08 · DASHBOARD")

    resp = http.get("/dashboard/")
    check("Dashboard (root)", resp, 200)

    resp = http.get("/dashboard/summary/")
    check("Dashboard Summary", resp, 200)

    resp = http.get("/dashboard/visit-trends/?days=30")
    check("Visit Trends (30 days)", resp, 200)

    resp = http.get("/dashboard/employee-performance/?days=30")
    check("Employee Performance (30 days)", resp, 200)

    resp = http.get("/dashboard/village-heatmap/?top=10")
    check("Village Heatmap", resp, 200)

    resp = http.get("/admin/dashboard/stats/")
    check("Dashboard Stats (Admin router)", resp, 200)


# ──────────────────────────────────────────────────────────────
# 9. REPORTS
# ──────────────────────────────────────────────────────────────
def test_reports():
    section("09 · REPORTS")

    start = (date.today() - timedelta(days=30)).isoformat()
    end = TODAY

    resp = http.get(f"/reports/employee-visits/?start_date={start}&end_date={end}")
    check("Employee Visit Report", resp, 200, require_success_flag=False)

    resp = http.get(f"/reports/village-visits/?start_date={start}&end_date={end}")
    check("Village Visit Report", resp, 200, require_success_flag=False)

    resp = http.get(f"/reports/crop-problems/?start_date={start}&end_date={end}")
    check("Crop Problem Report", resp, 200, require_success_flag=False)

    resp = http.get(f"/reports/daily/?date={TODAY}")
    check("Daily Report", resp, 200, require_success_flag=False)

    resp = http.get(
        f"/reports/monthly/?month={date.today().month}&year={date.today().year}"
    )
    check("Monthly Report", resp, 200, require_success_flag=False)


# ──────────────────────────────────────────────────────────────
# 10. NOTIFICATIONS
# ──────────────────────────────────────────────────────────────
def test_notifications():
    section("10 · NOTIFICATIONS")

    resp = http.get("/notifications/")
    _, body = check("List Notifications", resp, 200, require_success_flag=False)

    resp = http.get("/notifications/unread-count/")
    check("Unread Count", resp, 200)

    # Mark-all-read
    resp = http.post("/notifications/mark-all-read/", json={})
    check("Mark All Notifications Read", resp, 200)

    # Mark single read (only if there's a notification in the list)
    if body:
        notification_list = body.get("results") or (body.get("data") or [])
        if notification_list:
            nid = notification_list[0].get("id")
            if nid:
                state["notification_id"] = nid
                resp = http.post(f"/notifications/{nid}/read/", json={})
                check(f"Mark Notification {nid} Read", resp, 200)


# ──────────────────────────────────────────────────────────────
# 11. AUDIT LOGS
# ──────────────────────────────────────────────────────────────
def test_audit():
    section("11 · AUDIT LOGS")

    resp = http.get("/audit/logs/")
    check("List Audit Logs", resp, 200, require_success_flag=False)


# ──────────────────────────────────────────────────────────────
# 12. SYSTEM SETTINGS
# ──────────────────────────────────────────────────────────────
def test_system():
    section("12 · SYSTEM SETTINGS")

    resp = http.get("/system/settings/")
    check("Get System Settings", resp, 200, require_success_flag=False)

    resp = http.get("/system/config/")
    check("Get System Config", resp, 200, require_success_flag=False)


# ──────────────────────────────────────────────────────────────
# 13. MOBILE API
# ──────────────────────────────────────────────────────────────
def test_mobile():
    section("13 · MOBILE API")

    # Mobile login blocks is_staff users by design — use the employee created in test_employees()
    mob_username = state.get("employee_username")
    mob_password = state.get("employee_password")
    if not mob_username:
        print(yellow("  ⚠  No employee available — skipping mobile tests"))
        return

    # --- Mobile login ---
    resp = http.post(
        "/mobile/auth/login/",
        json={
            "username": mob_username,
            "password": mob_password,
        },
    )
    passed, body = check("Mobile Login", resp, 200, require_success_flag=False)
    if not passed:
        return

    mob_token = (body or {}).get("data", {}).get("access") or (body or {}).get("access")
    if not mob_token:
        record("Mobile Login — token extraction", False, "No 'access' key found")
        return

    # Override token for mobile calls
    http.set_token(mob_token)

    resp = http.get("/mobile/auth/me/")
    check("Mobile — Get Me", resp, 200)

    resp = http.get("/mobile/dashboard/")
    check("Mobile Dashboard", resp, 200)

    resp = http.get("/mobile/work/status/")
    check("Mobile Work Status", resp, 200)

    resp = http.get("/mobile/visits/stats/")
    check("Mobile Visit Stats", resp, 200)

    resp = http.get("/mobile/visits/?page=1&page_size=10")
    check("Mobile — List Visits", resp, 200, require_success_flag=False)

    resp = http.get("/mobile/reports/")
    check("Mobile Reports", resp, 200, require_success_flag=False)

    # Restore admin token
    http.set_token(state["admin_token"])


# ──────────────────────────────────────────────────────────────
# SUMMARY
# ──────────────────────────────────────────────────────────────
def print_summary():
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    bar = "═" * 60
    print(f"\n{cyan(bar)}")
    print(bold(cyan("  SUMMARY")))
    print(cyan(bar))
    print(f"  Total  : {bold(str(total))}")
    print(f"  {green('Passed')}: {bold(green(str(passed)))}")
    if failed:
        print(f"  {red('Failed')}: {bold(red(str(failed)))}")
        print(f"\n{red('  Failed tests:')}")
        for r in results:
            if not r["passed"]:
                detail = f" → {r['detail']}" if r["detail"] else ""
                print(f"    {red('✖')}  {r['name']}{grey(detail)}")
    else:
        print(f"\n  {green('All tests passed! 🎉')}")
    print(cyan(bar))

    return failed


# ──────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────
def main():
    print(bold(cyan("\n╔══════════════════════════════════════════════════════╗")))
    print(bold(cyan("║      Agri Clinic — Full API Test Suite              ║")))
    print(bold(cyan("╚══════════════════════════════════════════════════════╝")))
    print(f"  {grey('Base URL :')} {BASE_URL}")
    print(f"  {grey('Admin    :')} {ADMIN_USER}")
    print(f"  {grey('Run ID   :')} {RUN_ID}")
    print(f"  {grey('Date     :')} {TODAY}")

    try:
        test_auth()
        test_masters()
        test_employees()
        test_farmers()
        test_visits()
        test_tracking()
        test_tracking_admin()
        test_dashboard()
        test_reports()
        test_notifications()
        test_audit()
        test_system()
        test_mobile()
    except ConnectionError as exc:
        print(red(f"\n  ✖  {exc}"))
        sys.exit(2)
    except KeyboardInterrupt:
        print(yellow("\n\n  Interrupted by user."))

    failed = print_summary()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
