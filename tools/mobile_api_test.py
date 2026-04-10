#!/usr/bin/env python3
"""
Mobile API Integration Test
============================
Verifies the full authentication pipeline and protected endpoints for the
AgriClinic mobile API.

Usage:
    python tools/mobile_api_test.py
    python tools/mobile_api_test.py --base-url http://192.168.29.18:8000
    python tools/mobile_api_test.py --username ravi --password test1234
    python tools/mobile_api_test.py --employee-id EMP-001 --password test1234

Requirements:
    pip install requests
"""

import argparse
import json
import sys
from typing import Optional

import requests

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_USERNAME = "ravi"
DEFAULT_PASSWORD = "test1234"
TIMEOUT = 10

# ── ANSI colour helpers ───────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

PASS_LABEL = f"{GREEN}PASS{RESET}"
FAIL_LABEL = f"{RED}FAIL{RESET}"
WARN_LABEL = f"{YELLOW}WARN{RESET}"

# ── Result tracking ───────────────────────────────────────────────────────────
_results: list[tuple[str, str, str]] = []  # (label, status, note)


def _record(label: str, passed: bool, note: str = "") -> None:
    _results.append((label, "PASS" if passed else "FAIL", note))


# ── Pretty-print helpers ──────────────────────────────────────────────────────
def _body(r: requests.Response, max_chars: int = 400) -> str:
    try:
        text = json.dumps(r.json(), indent=2)
    except Exception:
        text = r.text or "(empty)"
    return text[:max_chars] + (" …(truncated)" if len(text) > max_chars else "")


def _sep(char: str = "─", width: int = 62) -> None:
    print(char * width)


def _heading(title: str) -> None:
    _sep("═")
    print(f"  {BOLD}{CYAN}{title}{RESET}")
    _sep("═")


def _ok(msg: str) -> None:
    print(f"  {GREEN}✔{RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}✘{RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {CYAN}→{RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def _check(
    r: requests.Response,
    label: str,
    expected: tuple[int, ...] = (200,),
    notes: str = "",
) -> bool:
    passed = r.status_code in expected
    tag = PASS_LABEL if passed else FAIL_LABEL
    print(f"\n  [{tag}] {label}")
    _info(f"HTTP {r.status_code}")
    _info(f"Body: {_body(r)}")
    if notes:
        _info(notes)
    _record(label, passed)
    return passed


# ── Step 0 — validate token locally using SimpleJWT ──────────────────────────
def _validate_token_locally(token: str, base_url: str) -> None:
    """
    Attempt to import Django + SimpleJWT and validate the token in-process.
    This only works when the script is run inside the project virtual-env.
    """
    _heading("STEP 0 — Local token validation (SimpleJWT)")
    try:
        import os, sys as _sys

        # Add project root to path so Django settings are discoverable
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in _sys.path:
            _sys.path.insert(0, project_root)
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

        import django

        django.setup()
        from rest_framework_simplejwt.tokens import AccessToken
        from rest_framework_simplejwt.exceptions import TokenError

        try:
            tok = AccessToken(token)
            _ok(f"Token is valid. user_id={tok['user_id']}  exp={tok['exp']}")
            _record("Token validation (local)", True)
        except TokenError as exc:
            _fail(f"Token rejected: {exc}")
            _record("Token validation (local)", False, str(exc))
    except Exception as exc:
        _warn(f"Could not perform local validation (Django unavailable): {exc}")
        _record("Token validation (local)", False, "Django unavailable")


# ── Step 1 — Login ────────────────────────────────────────────────────────────
def step_login(
    session: requests.Session,
    base: str,
    username: Optional[str],
    employee_id: Optional[str],
    password: str,
) -> Optional[str]:
    _heading("STEP 1 — Login")

    payload: dict = {"password": password}
    if employee_id:
        payload["employee_id"] = employee_id
        _info(f"POST {base}/api/v1/mobile/auth/login/  (employee_id={employee_id})")
    else:
        payload["username"] = username
        _info(f"POST {base}/api/v1/mobile/auth/login/  (username={username})")

    try:
        r = session.post(
            f"{base}/api/v1/mobile/auth/login/",
            json=payload,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        _fail(f"Network error: {exc}")
        _record("Login", False, str(exc))
        return None

    passed = _check(r, "Login", expected=(200,))
    if not passed:
        _fail("Cannot continue without an access token.")
        return None

    body = r.json()
    access = body.get("access") or body.get("access_token")
    refresh = body.get("refresh") or body.get("refresh_token")

    if not access:
        _fail(
            f"Login succeeded (HTTP 200) but no access token in response. Keys: {list(body.keys())}"
        )
        _record("Login — access token present", False, "Missing access key")
        return None

    _ok(f"access token length={len(access)}")
    _ok(
        f"refresh token present: {'yes' if refresh else 'NO — token refresh will be skipped'}"
    )

    user_block = body.get("user") or {}
    if user_block:
        _ok(
            f"user={user_block.get('username', '?')}  "
            f"employee_id={user_block.get('employee_id', '?')}"
        )

    # Attach token to session for all subsequent requests
    session.headers.update({"Authorization": f"Bearer {access}"})

    # Also test token refresh if we have a refresh token
    if refresh:
        _sep()
        _info("Testing token refresh …")
        try:
            r2 = requests.post(
                f"{base}/api/v1/mobile/auth/refresh/",
                json={"refresh": refresh},
                timeout=TIMEOUT,
            )
            _check(r2, "Token Refresh", expected=(200,))
        except requests.RequestException as exc:
            _warn(f"Refresh request failed: {exc}")
            _record("Token Refresh", False, str(exc))

    return access


# ── Step 2 — Auth Me ──────────────────────────────────────────────────────────
def step_auth_me(session: requests.Session, base: str) -> None:
    _heading("STEP 2 — GET /api/v1/mobile/auth/me/")
    _info(
        f"Authorization header: {session.headers.get('Authorization', 'NOT SET')[:60]}"
    )
    try:
        r = session.get(f"{base}/api/v1/mobile/auth/me/", timeout=TIMEOUT)
    except requests.RequestException as exc:
        _fail(f"Network error: {exc}")
        _record("Auth Me", False, str(exc))
        return

    passed = _check(r, "Auth Me", expected=(200,))
    if passed:
        data = r.json().get("data", {})
        _ok(
            f"username={data.get('username', '?')}  employee_id={data.get('employee_id', '?')}"
        )


# ── Step 3 — Dashboard ────────────────────────────────────────────────────────
def step_dashboard(session: requests.Session, base: str) -> None:
    _heading("STEP 3 — GET /api/v1/mobile/dashboard/")
    try:
        r = session.get(f"{base}/api/v1/mobile/dashboard/", timeout=TIMEOUT)
    except requests.RequestException as exc:
        _fail(f"Network error: {exc}")
        _record("Dashboard", False, str(exc))
        return

    passed = _check(r, "Dashboard", expected=(200,))
    if passed:
        data = r.json().get("data", {})
        _ok(
            f"work_status={data.get('work_status')}  "
            f"today_visits={data.get('today_visits')}  "
            f"completed={data.get('completed_visits')}  "
            f"pending={data.get('pending_visits')}"
        )


# ── Step 4 — Farmers list ─────────────────────────────────────────────────────
def step_farmers(session: requests.Session, base: str) -> None:
    _heading("STEP 4 — GET /api/v1/farmers/")
    try:
        r = session.get(f"{base}/api/v1/farmers/", timeout=TIMEOUT)
    except requests.RequestException as exc:
        _fail(f"Network error: {exc}")
        _record("Farmers List", False, str(exc))
        return

    # 200 = results returned; 403 = permission mismatch (still auth-passes)
    passed = _check(r, "Farmers List", expected=(200,))
    if passed:
        body = r.json()
        count = (
            body.get("count")
            if isinstance(body, dict)
            else len(body) if isinstance(body, list) else "?"
        )
        _ok(f"records_returned={count}")


# ── Step 5 — Visits list ──────────────────────────────────────────────────────
def step_visits(session: requests.Session, base: str) -> None:
    _heading("STEP 5 — GET /api/v1/visits/list/")
    try:
        r = session.get(f"{base}/api/v1/visits/list/", timeout=TIMEOUT)
    except requests.RequestException as exc:
        _fail(f"Network error: {exc}")
        _record("Visits List", False, str(exc))
        return

    passed = _check(r, "Visits List", expected=(200,))
    if passed:
        body = r.json()
        results = (
            body.get("results")
            if isinstance(body, dict)
            else body if isinstance(body, list) else []
        )
        _ok(f"records_returned={len(results) if results else body.get('count', '?')}")


# ── Step 6 — Additional mobile endpoints ─────────────────────────────────────
def step_extra_mobile(session: requests.Session, base: str) -> None:
    _heading("STEP 6 — Additional mobile endpoints")
    extra = [
        ("GET", f"{base}/api/v1/mobile/work/status/", "Work Status"),
        ("GET", f"{base}/api/v1/mobile/visits/stats/", "Mobile Visit Stats"),
    ]
    for method, url, label in extra:
        _info(f"{method} {url}")
        try:
            fn = session.get if method == "GET" else session.post
            r = fn(url, timeout=TIMEOUT)
            _check(r, label, expected=(200,))
        except requests.RequestException as exc:
            _fail(f"Network error: {exc}")
            _record(label, False, str(exc))


# ── Step 7 — Unauthenticated sanity check ─────────────────────────────────────
def step_unauth_sanity(base: str) -> None:
    _heading("STEP 7 — Unauthenticated request (must return 401)")
    _info(f"GET {base}/api/v1/mobile/auth/me/  (no token)")
    try:
        r = requests.get(f"{base}/api/v1/mobile/auth/me/", timeout=TIMEOUT)
    except requests.RequestException as exc:
        _fail(f"Network error: {exc}")
        _record("Unauth sanity (expect 401)", False, str(exc))
        return

    passed = r.status_code == 401
    tag = PASS_LABEL if passed else FAIL_LABEL
    print(f"\n  [{tag}] Unauth sanity (expect 401)")
    _info(f"HTTP {r.status_code}")
    _record("Unauth sanity (expect 401)", passed, f"got {r.status_code}")
    if not passed:
        _warn(
            "Expected 401 but got a different code — check DEFAULT_PERMISSION_CLASSES"
        )


# ── Final report ──────────────────────────────────────────────────────────────
def _print_report() -> int:
    _sep("═")
    print(f"\n{BOLD}  FINAL REPORT{RESET}\n")
    _sep()
    width_label = max(len(r[0]) for r in _results) + 2
    all_pass = True
    for label, status, note in _results:
        tag = PASS_LABEL if status == "PASS" else FAIL_LABEL
        suffix = f"  ← {note}" if note else ""
        print(f"  {label:<{width_label}} [{tag}]{suffix}")
        if status != "PASS":
            all_pass = False
    _sep()
    total = len(_results)
    passes = sum(1 for _, s, _ in _results if s == "PASS")
    fails = total - passes
    colour = GREEN if all_pass else RED
    print(
        f"\n  {colour}{BOLD}{passes}/{total} passed{RESET}"
        + (f"  ({fails} failed)" if fails else "")
    )
    print()
    return 0 if all_pass else 1


# ── CLI entry-point ───────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="AgriClinic Mobile API Integration Test"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Server base URL")
    parser.add_argument("--username", default=None, help="Django username")
    parser.add_argument(
        "--employee-id", default=None, help="Employee ID (e.g. EMP-001)"
    )
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password")
    parser.add_argument(
        "--skip-local-validation",
        action="store_true",
        help="Skip the in-process Django token validation step",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    username = args.username or (None if args.employee_id else DEFAULT_USERNAME)
    employee_id = args.employee_id
    password = args.password

    print(f"\n{BOLD}{CYAN}AgriClinic Mobile API Integration Test{RESET}")
    print(f"  Target: {base}")
    print(
        f"  Login:  {'employee_id=' + employee_id if employee_id else 'username=' + username}"
    )
    print()

    session = requests.Session()

    # ── Run steps ─────────────────────────────────────────────────────────────
    access_token = step_login(session, base, username, employee_id, password)
    if not access_token:
        print(
            f"\n{RED}Aborting — login failed, cannot test authenticated endpoints.{RESET}\n"
        )
        return _print_report()

    if not args.skip_local_validation:
        _validate_token_locally(access_token, base)

    step_auth_me(session, base)
    step_dashboard(session, base)
    step_farmers(session, base)
    step_visits(session, base)
    step_extra_mobile(session, base)
    step_unauth_sanity(base)

    return _print_report()


if __name__ == "__main__":
    sys.exit(main())
