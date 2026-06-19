#!/usr/bin/env python3
"""Verify Phase 1 tracking endpoints on Render production."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://agri-clinic-backend.onrender.com"


def get(path: str, timeout: int = 90):
    req = urllib.request.Request(
        BASE + path,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = raw[:300]
            return resp.status, data
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = raw[:300]
        return e.code, data


def main():
    print("Waiting for Render (cold start may take ~60s)...")
    health_ok = False
    for _ in range(12):
        try:
            code, body = get("/healthz/", timeout=30)
            if code == 200 and isinstance(body, dict) and body.get("database") == "ok":
                health_ok = True
                print("healthz:", body)
                break
        except Exception as exc:
            print("healthz retry:", exc)
        time.sleep(10)

    if not health_ok:
        print("FAIL: health check")
        sys.exit(1)

    code, body = get("/api/v1/tracking/admin/employee/1/daily-summary/")
    print("daily-summary:", code, body)
    daily_live = (
        code in (401, 403)
        or (code == 404 and isinstance(body, dict) and "Employee not found" in str(body.get("message", "")))
    )

    code, body = get("/api/v1/tracking/admin/employee/1/route/")
    print("route:", code, type(body))
    route_live = False
    if isinstance(body, dict):
        data = body.get("data") or {}
        route_live = "stops" in data
        print("route has stops key:", route_live)

    if daily_live and route_live:
        print("PASS: Phase 1 endpoints are live on Render")
        sys.exit(0)

    if not daily_live:
        print("FAIL: daily-summary endpoint not deployed yet (got", code, ")")
    if not route_live:
        print("FAIL: route stops[] not deployed yet")
    print("Tip: Render auto-deploy from main may still be building. Retry in 2-3 minutes.")
    sys.exit(1)


if __name__ == "__main__":
    main()
