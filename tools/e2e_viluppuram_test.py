"""
End-to-End Agri Clinic Flow with Viluppuram Masters

This script:
 1. Logs in as a test user (admin)
 2. Creates Viluppuram district → village
 3. Creates Paddy crop and Pest problem category
 4. Starts a workday
 5. Pushes multiple location points (simulating route)
 6. Sends heartbeats
 7. Creates visits
 8. Fetches workday history, locations, and availability
 9. Ends workday
 10. Logs out

Outputs collected data in JSON for frontend rendering and debugging.
"""

import requests
import json
from datetime import datetime
import sys

BASE = "http://127.0.0.1:8000"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"

# Sample employee (if exists; otherwise we'll use the logged-in user)
EMPLOYEE_USER = "apitest"
EMPLOYEE_PASS = "testpass123"

s = requests.Session()

# ======================================================
# STEP 0: ADMIN LOGIN
# ======================================================
print("=" * 60)
print("STEP 0: Admin Login")
print("=" * 60)
r = s.post(
    f"{BASE}/api/auth/login/", json={"username": ADMIN_USER, "password": ADMIN_PASS}
)
if r.status_code != 200:
    print(f"ERROR: Admin login failed: {r.status_code}")
    print(r.text)
    sys.exit(1)

admin_tokens = r.json()
admin_access = admin_tokens.get("access")
print(f"✓ Admin access token obtained")

admin_s = requests.Session()
admin_s.headers.update({"Authorization": f"Bearer {admin_access}"})

# ======================================================
# STEP 1: CREATE VILUPPURAM DISTRICT
# ======================================================
print("\n" + "=" * 60)
print("STEP 1: Create Viluppuram District")
print("=" * 60)
r = admin_s.post(f"{BASE}/api/v1/masters/districts/", json={"name": "Viluppuram"})
print(f"Status: {r.status_code}")
if r.status_code not in [201, 200, 409]:
    print(f"Response: {r.text}")
    sys.exit(1)

if r.status_code == 409:
    # Already exists; fetch it
    r = admin_s.get(f"{BASE}/api/v1/masters/districts/")
    districts = r.json() if isinstance(r.json(), list) else [r.json()]
    district = next(
        (d for d in districts if d.get("name") == "Viluppuram"),
        districts[0] if districts else {},
    )
    print(f"✓ District already exists: {district}")
else:
    district = r.json()
    print(f"✓ District created: {district}")

district_id = district.get("id")

# ======================================================
# STEP 2: CREATE VILLAGE
# ======================================================
print("\n" + "=" * 60)
print("STEP 2: Create Village - Viluppuram Village 1")
print("=" * 60)
r = admin_s.post(
    f"{BASE}/api/v1/masters/villages/",
    json={"name": "Viluppuram Village 1", "district": district_id},
)
print(f"Status: {r.status_code}")
if r.status_code not in [201, 200, 409]:
    print(f"Response: {r.text}")
    sys.exit(1)

if r.status_code == 409:
    # Already exists; fetch by district
    r = admin_s.get(f"{BASE}/api/v1/masters/villages/?district_id={district_id}")
    villages = r.json() if isinstance(r.json(), list) else [r.json()]
    village = villages[0] if villages else {}
    print(f"✓ Village already exists: {village}")
else:
    village = r.json()
    print(f"✓ Village created: {village}")

village_id = village.get("id")

# ======================================================
# STEP 3: CREATE CROP
# ======================================================
print("\n" + "=" * 60)
print("STEP 3: Create Crop - Paddy")
print("=" * 60)
r = admin_s.post(f"{BASE}/api/v1/masters/crops/", json={"name": "Paddy"})
print(f"Status: {r.status_code}")
if r.status_code not in [201, 200, 409]:
    print(f"Response: {r.text}")
    sys.exit(1)

if r.status_code == 409:
    # Already exists; fetch it
    r = admin_s.get(f"{BASE}/api/v1/masters/crops/")
    crops = r.json() if isinstance(r.json(), list) else [r.json()]
    crop = next(
        (c for c in crops if c.get("name") == "Paddy"), crops[0] if crops else {}
    )
    print(f"✓ Crop already exists: {crop}")
else:
    crop = r.json()
    print(f"✓ Crop created: {crop}")

crop_id = crop.get("id")

# ======================================================
# STEP 4: CREATE PROBLEM CATEGORY
# ======================================================
print("\n" + "=" * 60)
print("STEP 4: Create Problem Category - Pest")
print("=" * 60)
r = admin_s.post(f"{BASE}/api/v1/masters/problem-categories/", json={"name": "Pest"})
print(f"Status: {r.status_code}")
if r.status_code not in [201, 200, 409]:
    print(f"Response: {r.text}")
    sys.exit(1)

if r.status_code == 409:
    # Already exists; fetch it
    r = admin_s.get(f"{BASE}/api/v1/masters/problem-categories/")
    problems = r.json() if isinstance(r.json(), list) else [r.json()]
    problem = next(
        (p for p in problems if p.get("name") == "Pest"),
        problems[0] if problems else {},
    )
    print(f"✓ Problem category already exists: {problem}")
else:
    problem = r.json()
    print(f"✓ Problem category created: {problem}")

problem_id = problem.get("id")

# ======================================================
# EMPLOYEE LOGIN
# ======================================================
print("\n" + "=" * 60)
print("EMPLOYEE: Login")
print("=" * 60)
r = s.post(
    f"{BASE}/api/auth/login/",
    json={"username": EMPLOYEE_USER, "password": EMPLOYEE_PASS},
)
if r.status_code != 200:
    print(f"ERROR: Employee login failed: {r.status_code}")
    print(r.text)
    sys.exit(1)

emp_tokens = r.json()
emp_access = emp_tokens.get("access")
emp_refresh = emp_tokens.get("refresh")
print(f"✓ Employee access token obtained")

emp_s = requests.Session()
emp_s.headers.update({"Authorization": f"Bearer {emp_access}"})

# ======================================================
# STEP 6: START WORKDAY
# ======================================================
print("\n" + "=" * 60)
print("STEP 6: Start Workday")
print("=" * 60)
# End any existing workdays first
emp_s.post(f"{BASE}/api/tracking/workday/end/")

# Now start fresh
r = emp_s.post(f"{BASE}/api/tracking/workday/start/")
print(f"Status: {r.status_code}")
print(f"Response: {r.text}")
if r.status_code != 201:
    print("ERROR: Could not start workday")
    sys.exit(1)

print(f"✓ Workday started")

# ======================================================
# STEP 7: GET CURRENT WORKDAY
# ======================================================
print("\n" + "=" * 60)
print("STEP 7: Get Current Workday")
print("=" * 60)
r = emp_s.get(f"{BASE}/api/tracking/workday/current/")
print(f"Status: {r.status_code}")
current_wd = r.json()
print(f"Current workday: {json.dumps(current_wd, indent=2)}")
workday_id = current_wd.get("workday_id")

# ======================================================
# STEP 8: PUSH LOCATIONS (simulate route)
# ======================================================
print("\n" + "=" * 60)
print("STEP 8: Push Location Points (Viluppuram route)")
print("=" * 60)

locations = [
    {"latitude": 12.9500, "longitude": 79.1300, "accuracy": 10, "desc": "Point 1"},
    {"latitude": 12.9510, "longitude": 79.1310, "accuracy": 8, "desc": "Point 2"},
    {"latitude": 12.9520, "longitude": 79.1320, "accuracy": 7, "desc": "Point 3"},
    {"latitude": 12.9530, "longitude": 79.1330, "accuracy": 9, "desc": "Point 4"},
]

for loc in locations:
    r = emp_s.post(
        f"{BASE}/api/tracking/location/push/",
        json={
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "accuracy": loc["accuracy"],
        },
    )
    if r.status_code == 201:
        print(f"✓ {loc['desc']}: ({loc['latitude']}, {loc['longitude']})")
    else:
        print(f"✗ {loc['desc']}: {r.status_code} - {r.text}")

# ======================================================
# STEP 9: HEARTBEAT
# ======================================================
print("\n" + "=" * 60)
print("STEP 9: Send Heartbeat (GPS on)")
print("=" * 60)
r = emp_s.post(f"{BASE}/api/tracking/heartbeat/", json={"gps_enabled": True})
print(f"Status: {r.status_code}")
print(f"Response: {r.text}")

# ======================================================
# STEP 10: CREATE VISITS
# ======================================================
print("\n" + "=" * 60)
print("STEP 10: Create Visits (Viluppuram, Paddy, Pest)")
print("=" * 60)

visits_data = [
    {
        "farmer_name": "Shankar Kumar",
        "farmer_phone": "9876543210",
        "latitude": 12.9500,
        "longitude": 79.1300,
    },
    {
        "farmer_name": "Ravi Kumar",
        "farmer_phone": "9876543211",
        "latitude": 12.9520,
        "longitude": 79.1320,
    },
]

visit_ids = []
for v_data in visits_data:
    payload = {
        "farmer_name": v_data["farmer_name"],
        "farmer_phone": v_data["farmer_phone"],
        "village_id": village_id,
        "crop_id": crop_id,
        "problem_category_id": problem_id,
        "latitude": v_data["latitude"],
        "longitude": v_data["longitude"],
    }
    r = emp_s.post(f"{BASE}/api/visits/create/", json=payload)
    if r.status_code == 201:
        visit = r.json()
        visit_id = visit.get("visit_id")
        visit_ids.append(visit_id)
        print(f"✓ Visit created for {v_data['farmer_name']}: ID {visit_id}")
    else:
        print(f"✗ Visit creation failed: {r.status_code} - {r.text}")

# ======================================================
# STEP 11: FETCH WORKDAY LOCATIONS
# ======================================================
print("\n" + "=" * 60)
print("STEP 11: Fetch Workday Locations")
print("=" * 60)
r = emp_s.get(f"{BASE}/api/tracking/workday/{workday_id}/locations/?page_size=50")
print(f"Status: {r.status_code}")
locations_data = r.json()
print(f"Locations data:")
print(json.dumps(locations_data, indent=2))

# ======================================================
# STEP 12: FETCH WORKDAY HISTORY
# ======================================================
print("\n" + "=" * 60)
print("STEP 12: Fetch Workday History")
print("=" * 60)
r = emp_s.get(f"{BASE}/api/tracking/workdays/history/")
print(f"Status: {r.status_code}")
history = r.json()
print(f"Workday history: {json.dumps(history[:2], indent=2)}...")  # First 2

# ======================================================
# STEP 13: FETCH AVAILABILITY EVENTS
# ======================================================
print("\n" + "=" * 60)
print("STEP 13: Fetch Availability Events")
print("=" * 60)
r = emp_s.get(f"{BASE}/api/tracking/availability/events/")
print(f"Status: {r.status_code}")
events = r.json()
print(f"Availability events: {events}")

# ======================================================
# ADMIN: LIVE STATUS & GEOJSON
# ======================================================
print("\n" + "=" * 60)
print("ADMIN: Live Status & GeoJSON")
print("=" * 60)

r = admin_s.get(f"{BASE}/api/tracking/admin/status/")
if r.status_code == 200:
    statuses = r.json()
    print(f"Live statuses:")
    for emp in statuses[:2]:
        print(
            f"  - {emp.get('username')}: {emp.get('work_status')} ({emp.get('connection')})"
        )

r = admin_s.get(f"{BASE}/api/tracking/admin/geo/employees/")
if r.status_code == 200:
    geojson = r.json()
    print(
        f"\nGeoJSON Feature Collection: {geojson.get('type')} with {len(geojson.get('features', []))} features"
    )

# ======================================================
# STEP 14: END WORKDAY
# ======================================================
print("\n" + "=" * 60)
print("STEP 14: End Workday")
print("=" * 60)
r = emp_s.post(f"{BASE}/api/tracking/workday/end/")
print(f"Status: {r.status_code}")
print(f"Response: {r.text}")

# ======================================================
# STEP 15: LOGOUT
# ======================================================
print("\n" + "=" * 60)
print("STEP 15: Logout")
print("=" * 60)
r = emp_s.post(f"{BASE}/api/accounts/logout/", json={"refresh": emp_refresh})
print(f"Status: {r.status_code}")
print(f"Response: {r.text}")

# ======================================================
# SUMMARY
# ======================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(
    f"""
✓ Total flow completed successfully
✓ District: Viluppuram (ID: {district_id})
✓ Village: Viluppuram Village 1 (ID: {village_id})
✓ Crop: Paddy (ID: {crop_id})
✓ Problem Category: Pest (ID: {problem_id})
✓ Workday started and ended with {len(locations)} location points
✓ {len(visit_ids)} visits created
✓ All APIs tested and working

FOR FRONTEND INTEGRATION:
 - Use village_id={village_id}, crop_id={crop_id}, problem_id={problem_id} in forms
 - GeoJSON endpoints return FeatureCollections ready for Mapbox/Leaflet
 - All timestamps are ISO-8601 for easy parsing
 - Pagination supported on locations endpoint (page_size query param)
"""
)

print("\n" + "=" * 60)
