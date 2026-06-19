#!/usr/bin/env python3
"""Smoke test Render production API after deploy/restore."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://agri-clinic-backend.onrender.com/api/v1"


def req(method: str, path: str, body=None, headers=None, timeout=90):
    url = BASE + path
    data = None
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = raw
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = raw
        return e.code, parsed


def wait_health(max_wait=180):
    health_url = "https://agri-clinic-backend.onrender.com/healthz/"
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                if body.get("status") == "ok" and body.get("database") == "ok":
                    return True, body
        except Exception:
            pass
        time.sleep(10)
    return False, {}


def main():
    print("Waiting for Render health...")
    ok, health = wait_health()
    print("health", ok, health)
    if not ok:
        print("FAIL health check timeout")
        sys.exit(1)

    results = []

    code, data = req("GET", "/farmers/?page_size=1")
    results.append(("GET /farmers/", code, isinstance(data, dict)))

    code, data = req("GET", "/masters/villages/?page_size=1")
    results.append(("GET /masters/villages/", code, code == 200))

    code, data = req("GET", "/masters/crops/?page_size=1")
    results.append(("GET /masters/crops/", code, code == 200))

    code, data = req("GET", "/problem-items/?page_size=1")
    results.append(("GET /problem-items/", code, code == 200))

    # Employee login — set EMPLOYEE_ID + PASSWORD env or edit defaults for your deployment.
    import os

    employee_id = os.getenv("SMOKE_EMPLOYEE_ID", "RT-001")
    password = os.getenv("SMOKE_EMPLOYEE_PASSWORD", "x")
    code, login = req(
        "POST",
        "/mobile/auth/login/",
        {"employee_id": employee_id, "password": password},
    )
    results.append(("POST /mobile/auth/login/", code, code == 200 and "access" in login))
    token = login.get("access") if isinstance(login, dict) else None
    device = login.get("device_session_id") if isinstance(login, dict) else None

    if token and device:
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Device-Session": str(device),
        }
        code, me = req("GET", "/mobile/auth/me/", headers=headers)
        results.append(("GET /mobile/auth/me/", code, code == 200))

        code, dash = req("GET", "/mobile/dashboard/", headers=headers)
        results.append(
            (
                "GET /mobile/dashboard/",
                code,
                code == 200 and "visits_today" in (dash.get("data") or dash),
            )
        )

        code, _ = req("POST", "/tracking/workday/start/", {}, headers=headers)
        results.append(("POST /tracking/workday/start/", code, code in (200, 201, 400)))

        code, _ = req(
            "POST",
            "/tracking/location/push/",
            {
                "latitude": 12.9716,
                "longitude": 77.5946,
                "accuracy": 12,
                "speed": 1.2,
                "heading": 90,
            },
            headers=headers,
        )
        results.append(("POST /tracking/location/push/", code, code in (200, 201)))

    passed = sum(1 for _, code, ok in results if ok and code and code < 500)
    print("\nResults:")
    for name, code, ok in results:
        status = "PASS" if ok and code and code < 500 else "FAIL"
        print(f"  [{status}] {name} -> {code}")
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
