# Frontend API Documentation (Mobile + Admin)

Source analyzed:
- `docs/agri_mobile.postman_collection.json`
- `docs/agri_admin.postman_collection.json`
- `docs/agri_local_environment.json`

Base URL:
- `http://127.0.0.1:8000/api/v1`

Auth rule for protected APIs:
- Header: `Authorization: Bearer <access_token>`

Response note:
- Most business APIs return wrapper format:
  - `{ "success": true, "message": "...", "data": {...} }`

---

## 1) AUTH

### API 1
1. API Name: Mobile Login
2. Method: POST
3. Endpoint URL: `/api/v1/mobile/auth/login/`
4. Headers required:
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "employee_id": "EMP-101",
  "password": "Test@1234"
}
```
Required: `password`, and one of `employee_id` or `username`.
6. Response Structure (important fields only):
```json
{
  "access": "jwt_access_token",
  "refresh": "jwt_refresh_token",
  "user": {
    "id": 16,
    "username": "aravind.kumar",
    "employee_id": "EMP-101"
  }
}
```
7. Usage: Login screen (mobile app)

### API 2
1. API Name: Mobile Refresh Token
2. Method: POST
3. Endpoint URL: `/api/v1/mobile/auth/refresh/`
4. Headers required:
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "refresh": "jwt_refresh_token"
}
```
Required: `refresh`.
6. Response Structure (important fields only):
```json
{
  "access": "new_jwt_access_token"
}
```
7. Usage: Token interceptor / silent session renew

### API 3
1. API Name: Admin Login
2. Method: POST
3. Endpoint URL: `/api/v1/auth/login/`
4. Headers required:
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "username": "admin",
  "password": "admin123"
}
```
Required: `username`, `password`.
6. Response Structure (important fields only):
```json
{
  "access": "jwt_access_token",
  "refresh": "jwt_refresh_token",
  "user": {
    "id": 1,
    "username": "admin"
  }
}
```
7. Usage: Admin web login screen

### API 4
1. API Name: Admin Logout
2. Method: POST
3. Endpoint URL: `/api/v1/auth/logout/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "refresh": "jwt_refresh_token"
}
```
Required: `refresh`.
6. Response Structure (important fields only):
```json
{
  "success": true,
  "message": "Logout successful"
}
```
7. Usage: Logout action

---

## 2) DASHBOARD

### API 5
1. API Name: Mobile Dashboard
2. Method: GET
3. Endpoint URL: `/api/v1/mobile/dashboard/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "today_visits": 4,
    "completed_visits": 12,
    "pending_visits": 2,
    "active_visit": null
  }
}
```
7. Usage: Mobile home/dashboard screen

### API 6
1. API Name: Mobile Reports Summary
2. Method: GET
3. Endpoint URL: `/api/v1/mobile/reports/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "daily": 3,
    "monthly": 42
  }
}
```
7. Usage: Mobile analytics card / quick report widget

### API 7
1. API Name: Admin Dashboard Stats
2. Method: GET
3. Endpoint URL: `/api/v1/dashboard/stats/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "total_farmers": 120,
    "total_visits": 860,
    "active_employees": 14
  }
}
```
7. Usage: Admin dashboard main KPI cards

### API 8
1. API Name: Admin Visit Trends
2. Method: GET
3. Endpoint URL: `/api/v1/dashboard/visit-trends/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": [
    { "date": "2026-04-01", "count": 15 }
  ]
}
```
7. Usage: Admin charts screen

---

## 3) WORK MANAGEMENT

### API 9
1. API Name: Mobile Start Work
2. Method: POST
3. Endpoint URL: `/api/v1/mobile/work/start/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "latitude": 11.6643,
  "longitude": 78.146
}
```
Required: none. Optional: `latitude`, `longitude`.
6. Response Structure (important fields only):
```json
{
  "success": true,
  "message": "Workday started"
}
```
7. Usage: Start shift button

### API 10
1. API Name: Mobile Stop Work
2. Method: POST
3. Endpoint URL: `/api/v1/mobile/work/stop/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "message": "Workday stopped"
}
```
7. Usage: End shift button

### API 11
1. API Name: Mobile Work Status
2. Method: GET
3. Endpoint URL: `/api/v1/mobile/work/status/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "work_status": "started"
  }
}
```
7. Usage: Home screen status badge

### API 12
1. API Name: Tracking Workday Start (Legacy Flow)
2. Method: POST
3. Endpoint URL: `/api/v1/tracking/workday/start/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "message": "Workday started"
}
```
7. Usage: Legacy tracking clients

### API 13
1. API Name: Tracking Workday End (Legacy Flow)
2. Method: POST
3. Endpoint URL: `/api/v1/tracking/workday/end/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "message": "Workday ended",
  "ended_count": 1
}
```
7. Usage: Legacy tracking clients

---

## 4) VISITS

### API 14
1. API Name: List My Visits
2. Method: GET
3. Endpoint URL: `/api/v1/mobile/visits/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": [
    {
      "id": 101,
      "farmer_name": "Ravi Kumar",
      "status": "scheduled",
      "visit_date": "2026-04-11"
    }
  ]
}
```
7. Usage: Visit list screen

### API 15
1. API Name: Start Visit
2. Method: POST
3. Endpoint URL: `/api/v1/visits/start/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "crop": 1,
  "latitude": 11.6643,
  "longitude": 78.146,
  "farmer_name": "Ravi Kumar",
  "village": 1,
  "notes": "Crop inspection visit"
}
```
Required: `crop`, `latitude`, `longitude`, `farmer_name`, `village`.
Optional: `notes`.
6. Response Structure (important fields only):
```json
{
  "visit_id": 245
}
```
7. Usage: Visit start form

### API 16
1. API Name: Complete Visit
2. Method: POST
3. Endpoint URL: `/api/v1/visits/{visit_id}/complete/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "notes": "Inspection completed. Fertilizer recommended."
}
```
Required: `notes`.
6. Response Structure (important fields only):
```json
{
  "success": true,
  "message": "Visit completed"
}
```
7. Usage: Visit completion action

### API 17
1. API Name: Upload Visit Media
2. Method: POST
3. Endpoint URL: `/api/v1/visits/{visit_id}/upload-media/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: multipart/form-data`
5. Request Body (clean JSON):
```json
{
  "file": "<binary>",
  "media_type": "image",
  "caption": "Field photo - north plot"
}
```
Required: `file`. Optional: `media_type`, `caption`.
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "id": 45,
    "media_url": "https://..."
  }
}
```
7. Usage: Visit media upload component

### API 18
1. API Name: Mobile Visit Stats
2. Method: GET
3. Endpoint URL: `/api/v1/mobile/visits/stats/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "today_visits": 3,
    "completed": 2,
    "pending": 1
  }
}
```
7. Usage: Visit stats card

### API 19
1. API Name: Admin Visit List
2. Method: GET
3. Endpoint URL: `/api/v1/admin/visits/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "count": 520,
  "results": [
    {
      "id": 245,
      "farmer_name": "Ravi Kumar",
      "employee_name": "aravind.kumar",
      "status": "completed"
    }
  ]
}
```
7. Usage: Admin visits table

---

## 5) TRACKING

### API 20
1. API Name: Push Location (Single)
2. Method: POST
3. Endpoint URL: `/api/v1/tracking/location/push/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "latitude": 11.6643,
  "longitude": 78.146,
  "accuracy": 10,
  "recorded_at": "2026-04-11T18:00:00Z"
}
```
Required: `latitude`, `longitude`. Optional: `accuracy`, `recorded_at`.
6. Response Structure (important fields only):
```json
{
  "message": "Location saved",
  "location": {
    "latitude": "11.664300",
    "longitude": "78.146000",
    "recorded_at": "2026-04-11T18:00:00Z"
  }
}
```
7. Usage: Foreground live tracking service

### API 21
1. API Name: Push Location (Bulk Sync)
2. Method: POST
3. Endpoint URL: `/api/v1/tracking/location/bulk/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "locations": [
    {
      "latitude": 11.6643,
      "longitude": 78.146,
      "accuracy": 12,
      "recorded_at": "2026-04-11T18:00:00Z"
    }
  ]
}
```
Required: `locations[]` with `latitude`, `longitude`.
Optional per location: `accuracy`, `recorded_at`, `battery_level`, `network_type`.
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "created": [13, 14],
    "errors": []
  }
}
```
7. Usage: Offline sync queue uploader

### API 22
1. API Name: Mobile Tracking Ping
2. Method: POST
3. Endpoint URL: `/api/v1/mobile/tracking/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
   - `Content-Type: application/json`
5. Request Body (clean JSON):
```json
{
  "latitude": 11.6643,
  "longitude": 78.146,
  "accuracy": 15
}
```
Required: `latitude`, `longitude`.
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "location_id": 99
  }
}
```
7. Usage: Mobile location ping API

### API 23
1. API Name: Heartbeat
2. Method: POST
3. Endpoint URL: `/api/v1/tracking/heartbeat/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{
  "gps_enabled": true
}
```
Required: `gps_enabled`.
6. Response Structure (important fields only):
```json
{
  "message": "Heartbeat received"
}
```
7. Usage: Background health pings

### API 24
1. API Name: Admin Tracking Status
2. Method: GET
3. Endpoint URL: `/api/v1/tracking/admin/status/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": [
    {
      "user_id": 16,
      "employee_id": "EMP-101",
      "status": "online",
      "last_seen": "2026-04-11T18:10:00Z"
    }
  ]
}
```
7. Usage: Admin live employee monitor screen

### API 25
1. API Name: Admin Employee Route
2. Method: GET
3. Endpoint URL: `/api/v1/tracking/admin/employee/{user_id}/route/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "user_id": 16,
    "points": [
      { "latitude": 11.6643, "longitude": 78.146, "recorded_at": "2026-04-11T18:00:00Z" }
    ]
  }
}
```
7. Usage: Admin route replay map

---

## 6) MASTERS (CROPS, VILLAGES)

### API 26
1. API Name: List Districts
2. Method: GET
3. Endpoint URL: `/api/v1/masters/districts/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "results": [
      { "id": 1, "name": "Viluppuram" }
    ]
  }
}
```
7. Usage: District dropdown

### API 27
1. API Name: List Villages
2. Method: GET
3. Endpoint URL: `/api/v1/masters/villages/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "results": [
      { "id": 1, "name": "Tindivanam", "district": 1 }
    ]
  }
}
```
7. Usage: Village dropdown (dependent on district)

### API 28
1. API Name: List Crops
2. Method: GET
3. Endpoint URL: `/api/v1/masters/crops/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "results": [
      { "id": 1, "name_en": "Paddy", "name_ta": "Nel" }
    ]
  }
}
```
7. Usage: Crop selector

### API 29
1. API Name: Admin Crop Catalog List
2. Method: GET
3. Endpoint URL: `/api/v1/admin/crop-catalog/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "count": 45,
  "results": [
    { "id": 1, "name_en": "Paddy", "is_active": true }
  ]
}
```
7. Usage: Admin crop management table

---

## 7) PROFILE

### API 30
1. API Name: Mobile My Profile
2. Method: GET
3. Endpoint URL: `/api/v1/mobile/auth/me/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "id": 16,
    "username": "aravind.kumar",
    "employee_id": "EMP-101",
    "phone": "9876543210"
  }
}
```
7. Usage: Mobile profile screen

### API 31
1. API Name: Employee Me (Admin/Auth Context)
2. Method: GET
3. Endpoint URL: `/api/v1/employees/me/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "data": {
    "id": 16,
    "username": "aravind.kumar",
    "role": "FieldAgent",
    "employee_id": "EMP-101"
  }
}
```
7. Usage: Web profile menu / role-driven UI

---

## 8) NOTIFICATIONS

### API 32
1. API Name: List Notifications
2. Method: GET
3. Endpoint URL: `/api/v1/notifications/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "count": 24,
  "results": [
    {
      "id": 1001,
      "title": "Visit overdue",
      "is_read": false,
      "created_at": "2026-04-11T17:00:00Z"
    }
  ]
}
```
7. Usage: Notification center list

### API 33
1. API Name: Unread Notification Count
2. Method: GET
3. Endpoint URL: `/api/v1/notifications/unread-count/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "unread_count": 5
}
```
7. Usage: App bar badge count

### API 34
1. API Name: Mark Notification Read
2. Method: POST
3. Endpoint URL: `/api/v1/notifications/{notification_id}/read/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "message": "Marked as read"
}
```
7. Usage: Notification item tap action

### API 35
1. API Name: Mark All Notifications Read
2. Method: POST
3. Endpoint URL: `/api/v1/notifications/mark-all-read/`
4. Headers required:
   - `Authorization: Bearer <access_token>`
5. Request Body (clean JSON):
```json
{}
```
6. Response Structure (important fields only):
```json
{
  "success": true,
  "message": "All notifications marked as read"
}
```
7. Usage: Mark all as read action

---

## Quick Integration Notes

1. Mobile app should use `/api/v1/mobile/*` for auth/profile/dashboard/work where available.
2. Use `/api/v1/tracking/location/bulk/` for offline location sync batches.
3. `Authorization` must use `Bearer` prefix only.
4. For protected APIs, first run login and store `access` + `refresh` from top-level response keys.
5. Replace all path params (`{visit_id}`, `{user_id}`, `{notification_id}`) before request.
