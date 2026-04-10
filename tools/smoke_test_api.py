import requests
import sys

BASE = "http://127.0.0.1:8000"
USERNAME = "apitest"
PASSWORD = "testpass123"

s = requests.Session()

print("Logging in...")
r = s.post(f"{BASE}/api/auth/login/", json={"username": USERNAME, "password": PASSWORD})
print(r.status_code, r.text)
if r.status_code != 200:
    print("Login failed; aborting")
    sys.exit(1)

tokens = r.json()
access = tokens.get("access")
refresh = tokens.get("refresh")
if not access:
    print("No access token in response; aborting")
    sys.exit(1)

s.headers.update({"Authorization": f"Bearer {access}"})

# Start workday
print("\nStart workday")
r = s.post(f"{BASE}/api/tracking/workday/start/")
print(r.status_code, r.text)

# Heartbeat
print("\nHeartbeat")
r = s.post(f"{BASE}/api/tracking/heartbeat/", json={"gps_enabled": True})
print(r.status_code, r.text)

# Push location
print("\nPush location")
r = s.post(
    f"{BASE}/api/tracking/location/push/",
    json={"latitude": 12.9716, "longitude": 77.5946, "accuracy": 5},
)
print(r.status_code, r.text)

# Create visit (requires master ids; will attempt and report)
print("\nCreate visit")
r = s.post(
    f"{BASE}/api/visits/create/",
    json={
        "farmer_name": "Test Farmer",
        "farmer_phone": "9999999999",
        "village_id": 1,
        "crop_id": 1,
        "problem_category_id": 1,
        "latitude": 12.9716,
        "longitude": 77.5946,
    },
)
print(r.status_code, r.text)

# Admin status (should 403 for non-admin)
print("\nAdmin status (expected 403)")
r = s.get(f"{BASE}/api/tracking/admin/status/")
print(r.status_code, r.text)

# Current workday
print("\nCurrent workday")
r = s.get(f"{BASE}/api/tracking/workday/current/")
print(r.status_code, r.text)

# Workday history
print("\nWorkday history")
r = s.get(f"{BASE}/api/tracking/workdays/history/")
print(r.status_code, r.text)

# If current workday exists, fetch locations
try:
    cur = r = s.get(f"{BASE}/api/tracking/workday/current/")
    if cur.status_code == 200:
        jd = cur.json()
        wid = jd.get("workday_id")
        if wid:
            print("\nWorkday locations (first page)")
            r = s.get(f"{BASE}/api/tracking/workday/{wid}/locations/?page_size=10")
            print(r.status_code, r.text)
except Exception:
    pass

# Availability events
print("\nAvailability events")
r = s.get(f"{BASE}/api/tracking/availability/events/")
print(r.status_code, r.text)

# Logout (instructs client to discard tokens, optionally blacklists refresh)
print("\nLogout")
r = s.post(f"{BASE}/api/accounts/logout/", json={"refresh": refresh})
print(r.status_code, r.text)

print("\nSmoke test finished")
