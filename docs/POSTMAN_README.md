# Agri Clinic API - Postman Collection & Frontend Integration Guide

This guide explains how to use the Postman collection and integrate the APIs with your frontend (React/Vue/Angular) admin panel and mobile app.

## Quick Start

### Prerequisites
- Postman (desktop or web)
- Running Agri Clinic backend: `python manage.py runserver 0.0.0.0:8000`
- A test user for employee API testing

### Import Collection & Environment

1. **Download Files**
   - `docs/postman_agri_clinic_collection.json` — Main API collection
   - `docs/postman_agri_clinic_environment.json` — Environment with variables

2. **Import into Postman**
   - Open Postman → Collections → Import
   - Select `postman_agri_clinic_collection.json`
   - Open Environments section → Import
   - Select `postman_agri_clinic_environment.json`

3. **Select Environment**
   - Top-right corner: choose "Agri Clinic - Local"

## API Structure

### Modules

#### 1. **Auth** — Authentication & Tokens
```
POST   /api/auth/login/              → Obtain JWT access + refresh tokens
POST   /api/auth/refresh/             → Refresh expired access token
```

**Login Request Body:**
```json
{
  "username": "admin",
  "password": "admin"
}
```

**Response:**
```json
{
  "refresh": "eyJ0...",  // Store in env as {{refresh_token}}
  "access": "eyJ0..."    // Store in env as {{access_token}}
}
```

**Setup in Postman:**
- After login, copy `access` → Environment variable `access_token`
- Copy `refresh` → Environment variable `refresh_token`
- Or use a **Pre-request Script** to auto-extract (see Collections/Auth/Login test script)

#### 2. **Accounts** — User & Employee Management
```
GET    /api/accounts/me/                  → Current user profile
GET    /api/accounts/employees/           → List all employees (admin only)
GET    /api/accounts/employees/<id>/      → Get employee detail
POST   /api/accounts/logout/              → Logout (optional blacklist)
```

**Logout Request Body:**
```json
{
  "refresh": "{{refresh_token}}"
}
```

#### 3. **Tracking** — Location & Workday Management

**Employee (Mobile) Endpoints:**
```
POST   /api/tracking/workday/start/       → Start workday (blocks duplicate starts)
POST   /api/tracking/workday/end/         → End all active workdays
POST   /api/tracking/heartbeat/           → Ping (update last_heartbeat + GPS event)
POST   /api/tracking/location/push/       → Push GPS point (validated for accuracy/jump)
GET    /api/tracking/workday/current/     → Get current active workday + last location
GET    /api/tracking/workday/<id>/locations/?page_size=50  → Paginated location history
GET    /api/tracking/workdays/history/    → All workday sessions for user
GET    /api/tracking/availability/events/ → GPS off/online events
```

**Admin Endpoints:**
```
GET    /api/tracking/admin/status/        → Live status of all employees
GET    /api/tracking/admin/geo/employees/ → GeoJSON FeatureCollection (points + metadata)
GET    /api/tracking/admin/geo/routes/<user_id>/?date=2026-02-21
       → GeoJSON Feature with LineString (employee route for date)
GET    /api/tracking/admin/geo/last_location/<user_id>/
       → Last location of employee (lat/lng + timestamp)
```

**Sample: Push Location**
```json
{
  "latitude": 12.9716,
  "longitude": 77.5946,
  "accuracy": 5
}
```

**Validations:**
- `accuracy <= 50 meters` (rejections: GPS off-screen, indoor)
- `GPS jump detection`: distance between consecutive points > 5 km → rejected
- `Active workday required`

#### 4. **Visits** — Farmer Visit Records
```
POST   /api/visits/create/                → Create visit (requires active workday)
GET    /api/visits/list/                  → List visits (employee: own; admin: all)
POST   /api/visits/visits/<id>/attachments/  → Upload file (crop photo, bill, etc.)
GET    /api/visits/attachments/<id>/download/ → Download attachment
```

**Create Visit Request:**
```json
{
  "farmer_name": "Shankar Kumar",
  "farmer_phone": "9876543210",
  "village_id": 5,           // From setup collection
  "crop_id": 1,              // Paddy
  "problem_category_id": 2,  // Pest
  "latitude": 12.9500,
  "longitude": 79.1300
}
```

#### 5. **Masters** — Reference Data (Districts, Taluks, Villages, Crops, Problems)
```
GET    /api/v1/masters/districts/               → List all districts
GET    /api/v1/masters/taluks/?district_id=5   → Filter taluks by district
GET    /api/v1/masters/villages/?taluk_id=3    → Filter villages by taluk
GET    /api/v1/masters/crops/                   → List crops
GET    /api/v1/masters/problem-categories/     → List problem categories
```

**Admin Create Endpoint:**
```
POST   /api/v1/masters/districts/
POST   /api/v1/masters/taluks/
POST   /api/v1/masters/villages/
POST   /api/v1/masters/crops/
POST   /api/v1/masters/problem-categories/
```

---

## Viluppuram Test Data Collection

The collection includes a **Setup: Viluppuram Masters** folder with requests to:
1. Create Viluppuram district
2. Create Viluppuram Taluk
3. Create Viluppuram Village 1
4. Create Paddy crop
5. Create Pest problem category
6. Verify village list

**Use this flow** to generate test data for your frontend development:

1. Login (Auth folder)
2. Run **Setup: Viluppuram Masters** requests in order
3. Each request has a **post-request test script** that extracts IDs and stores them in environment variables
4. Variables auto-populated: `village_id`, `crop_id`, `problem_id`
5. Visit create request now uses these variables → forms can use them

---

## Complete End-to-End Test Flow

Run `tools/e2e_viluppuram_test.py` to test the entire flow:

```bash
python tools/e2e_viluppuram_test.py
```

This script:
1. Logs in as admin
2. Creates/fetches Viluppuram masters (district, taluk, village, crop, problem)
3. Logs in as employee
4. Starts a workday
5. Pushes 4 location points (simulating a field route)
6. Sends heartbeat
7. Creates 2 visitor records
8. Fetches workday history, locations, availability
9. Admin: fetches live statuses and GeoJSON
10. Ends workday and logs out

**Output:** Shows collected data structures ready for frontend rendering

---

## Frontend Integration Examples

### React Example: Fetch Current Workday & Display Map

```jsx
import React, { useEffect, useState } from 'react';
import L from 'leaflet'; // Mapbox or Leaflet

const EmployeeTracker = ({ accessToken }) => {
  const [workday, setWorkday] = useState(null);
  const [map, setMap] = useState(null);

  useEffect(() => {
    // Fetch current workday
    fetch('http://localhost:8000/api/tracking/workday/current/', {
      headers: { Authorization: `Bearer ${accessToken}` }
    })
      .then(r => r.json())
      .then(data => {
        setWorkday(data);
        
        // Fetch and display route
        fetch(`http://localhost:8000/api/tracking/workday/${data.workday_id}/locations/`, {
          headers: { Authorization: `Bearer ${accessToken}` }
        })
          .then(r => r.json())
          .then(locData => {
            // Plot locations on map
            const coordinates = locData.results.map(p => [p.latitude, p.longitude]);
            // L.polyline(coordinates).addTo(map);
          });
      });
  }, [accessToken]);

  return (
    <div>
      {workday && (
        <>
          <p>Workday: {workday.workday_id}</p>
          <p>Last Heartbeat: {workday.last_heartbeat}</p>
          <p>Current Location: {workday.last_location?.latitude}, {workday.last_location?.longitude}</p>
          <div id="map" style={{ width: '100%', height: '500px' }}></div>
        </>
      )}
    </div>
  );
};

export default EmployeeTracker;
```

### Admin Panel: GeoJSON on Map (Mapbox GL JS)

```jsx
const AdminMap = ({ accessToken }) => {
  useEffect(() => {
    // Fetch all employees as GeoJSON
    fetch('http://localhost:8000/api/tracking/admin/geo/employees/', {
      headers: { Authorization: `Bearer ${accessToken}` }
    })
      .then(r => r.json())
      .then(geojson => {
        // Add to Mapbox source
        map.addSource('employees', { type: 'geojson', data: geojson });
        map.addLayer({
          id: 'employees',
          type: 'circle',
          source: 'employees',
          paint: {
            'circle-radius': 8,
            'circle-color': [
              'match',
              ['get', 'work_status'],
              'WORKING', '#00ff00',
              'NOT_WORKING', '#ff0000',
              '#999'
            ]
          }
        });

        // On click, fetch and show route
        map.on('click', 'employees', (e) => {
          const userId = e.features[0].properties.employee_id;
          const date = new Date().toISOString().split('T')[0];
          fetch(`http://localhost:8000/api/tracking/admin/geo/routes/${userId}/?date=${date}`, {
            headers: { Authorization: `Bearer ${accessToken}` }
          })
            .then(r => r.json())
            .then(lineFeature => {
              map.addSource('route', { type: 'geojson', data: lineFeature });
              map.addLayer({
                id: 'route',
                type: 'line',
                source: 'route',
                paint: { 'line-color': '#ff0000', 'line-width': 2 }
              });
            });
        });
      });
  }, []);

  return <div id="map" style={{ width: '100%', height: '100vh' }} />;
};
```

### Mobile: Start Workday & Push Locations Periodically

```javascript
// Start workday
async function startWorkday(accessToken) {
  const res = await fetch('http://localhost:8000/api/tracking/workday/start/', {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` }
  });
  return res.json();
}

// Push location every 30 seconds
function startLocationTracking(accessToken) {
  setInterval(async () => {
    const { coords } = await getCurrentPosition(); // Geolocation API
    await fetch('http://localhost:8000/api/tracking/location/push/', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        latitude: coords.latitude,
        longitude: coords.longitude,
        accuracy: coords.accuracy
      })
    });
  }, 30000);
}

// Heartbeat every 5 minutes (keep session alive)
function sendHeartbeat(accessToken) {
  setInterval(async () => {
    await fetch('http://localhost:8000/api/tracking/heartbeat/', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ gps_enabled: true })
    });
  }, 5 * 60 * 1000);
}
```

---

## Environment Variables

The environment file supports:

| Variable | Purpose | Example |
|----------|---------|---------|
| `base_url` | API server | `http://localhost:8000` |
| `access_token` | JWT access token | (auto-populated after login) |
| `refresh_token` | JWT refresh token | (auto-populated after login) |
| `district_id` | Viluppuram district ID | `5` (set by setup collection) |
| `taluk_id` | Viluppuram taluk ID | `3` |
| `village_id` | Viluppuram village ID | `5` |
| `crop_id` | Paddy crop ID | `1` |
| `problem_id` | Pest problem ID | `2` |

**Usage in Requests:**
```
POST /api/visits/create/
{
  "village_id": {{village_id}},
  "crop_id": {{crop_id}},
  "problem_category_id": {{problem_id}},
  ...
}
```

---

## API Response Formats

### GeoJSON Response (Admin Employees)
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "employee_id": "EMP001",
        "username": "apitest",
        "phone": "9876543210",
        "work_status": "WORKING",
        "connection": "ONLINE",
        "gps_status": "GPS_ON",
        "last_seen": "2026-02-21T08:35:22.318899Z"
      },
      "geometry": {
        "type": "Point",
        "coordinates": [79.130000, 12.950000]  // [lon, lat]
      }
    }
  ]
}
```

### Route Response (Admin Employee Route)
```json
{
  "type": "Feature",
  "properties": {
    "user_id": 5,
    "date": "2026-02-21"
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [79.130000, 12.950000],
      [79.131000, 12.951000],
      [79.132000, 12.952000],
      [79.133000, 12.953000]
    ]
  }
}
```

### Paginated Locations Response
```json
{
  "count": 4,
  "next": null,
  "previous": null,
  "results": [
    {
      "latitude": "12.950000",
      "longitude": "79.130000",
      "accuracy": 10.0,
      "recorded_at": "2026-02-21T02:43:45.041208-06:00"
    },
    ...
  ]
}
```

---

## Error Handling

Common HTTP Status Codes:

| Code | Meaning | Action |
|------|---------|--------|
| 200 | OK | Data valid |
| 201 | Created | Resource created |
| 400 | Bad Request | Invalid parameters; check body schema |
| 401 | Unauthorized | Token expired or missing; refresh or re-login |
| 403 | Forbidden | Insufficient permissions (e.g., admin required) |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Duplicate data or invalid state (e.g., workday already started) |
| 500 | Server Error | Internal error; check server logs |

**Example Error Response:**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_DATA",
    "message": "Request failed",
    "details": {
      "detail": "GPS jump detected, jump_km: 10.50"
    }
  }
}
```

---

## Testing Workflow

### 1. Local Development
```bash
# Terminal 1: Start backend
python manage.py runserver 0.0.0.0:8000

# Terminal 2: Run smoke test
python tools/smoke_test_api.py

# Terminal 3: Run E2E test with Viluppuram data
python tools/e2e_viluppuram_test.py
```

### 2. Postman Collection Tests
- Import `postman_agri_clinic_collection.json`
- Import `postman_agri_clinic_environment.json`
- Open "Setup: Viluppuram Masters" folder
- Run requests in order
- Check that test scripts pass (green checkmark)

### 3. Frontend Development
- Use the GeoJSON endpoints to render maps
- Use pagination for large location histories
- Poll `/heartbeat/` every 5 minutes to keep session alive
- Poll `/location/push/` every 30 seconds during active work

---

## Deployment Notes

### Production Environment Variables
Update `postman_agri_clinic_environment.json` for production:
```json
{
  "base_url": "https://agri-clinic-backend.onrender.com"
}
```

### CORS Headers
Backend is configured to accept:
- `http://localhost:5173` (Vite dev)
- `https://agri-clinic-frontend.onrender.com` (prod)

Update `config/settings.py` if frontend domain changes.

### Database
- Migrations auto-applied on deploy
- Supports both SQLite (dev) and PostgreSQL (prod)

---

## Support & Troubleshooting

**Q: Token expired, what now?**
A: Use refresh endpoint or re-login to get new access token.

**Q: GPS jump detected (error 400) on location push**
A: Coordinates jumped >5km; retry with valid GPS or check user location.

**Q: Low accuracy (error 400)**
A: GPS accuracy >50m; wait for GPS lock or use different location.

**Q: Workday already started (error 400)**
A: Another workday is active; end it first before restarting.

**Q: GeoJSON not rendering on map**
A: Ensure coordinates are in [longitude, latitude] order; double-check API response format.

---

## API Documentation

Full OpenAPI docs available at:
```
http://localhost:8000/api/docs/
```

---

**Last Updated:** February 21, 2026  
**Backend Version:** Agri Clinic v1.0  
**Collection Version:** Postman v2.1.0
