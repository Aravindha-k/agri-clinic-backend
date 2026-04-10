# Agri Clinic API — Usage Guide

## Base URL

```
http://127.0.0.1:8000/api/v1
```

---

## Authentication

All endpoints (except login) require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Admin Login

```http
POST /api/v1/auth/login/
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```

**Response** (raw JWT — NOT wrapped in success/data):

```json
{
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>",
  "user": {"id": 1, "username": "admin"},
  "employee": {"id": 1, "employee_id": "EMP001", "name": "Admin User", "role": "admin", "district": "Viluppuram"}
}
```

### Mobile Login

```http
POST /api/v1/mobile/auth/login/
Content-Type: application/json

{
  "employee_id": "EMP001",
  "password": "pass1234"
}
```

> Both `employee_id` and `username` are accepted on the mobile login endpoint.

---

## Standard Response Format

```json
{"success": true, "message": "Operation successful", "data": {...}}
```

Error:

```json
{"success": false, "message": "Validation error", "error": {"code": "VALIDATION_ERROR", "details": {"field": ["error message"]}}}
```

---

## Key Endpoints

### Create Farmer
```http
POST /api/v1/farmers/
{"name": "Ravi Kumar", "phone": "9876543210", "district": 1, "village": 3, "total_land_area": 3.5, "irrigation_type": "borewell", "soil_type": "red"}
```
> district and village are integer FK IDs — not names.

### Create Farmer Field
```http
POST /api/v1/farmers/{id}/fields/
{"land_name": "North Plot", "land_size": 1.5, "soil_type": "red", "irrigation_type": "borewell", "gps_location": "11.6643,78.1460"}
```
> Use `land_name`, `land_size`, `gps_location` — NOT `field_name`, `field_size`, `gps_polygon`.

### Create Crop (Masters)
```http
POST /api/v1/masters/crops/
{"name_en": "Paddy", "name_ta": "நெல்", "scientific_name": "Oryza sativa", "crop_category": "cereal", "typical_season": "kharif"}
```
> Use `name_en` and `name_ta` — NOT `name`.

### Start Visit
```http
POST /api/v1/visits/start/
{"crop": 1, "latitude": 11.6643, "longitude": 78.1460, "farmer_name": "Ravi Kumar", "village": 3}
```
> Visit stores `farmer_name` as a CharField — there is NO FK to the Farmer model.

### Upload Visit Media
```http
POST /api/v1/visits/{id}/upload-media/
Content-Type: multipart/form-data
file=<binary> media_type=image caption=Field photo
```

---

## Field Name Reference

| Model       | Correct           | Wrong (do NOT use)   |
|-------------|-------------------|----------------------|
| FarmerField | `land_name`       | `field_name`         |
| FarmerField | `land_size`       | `field_size`         |
| FarmerField | `gps_location`    | `gps_polygon`        |
| Crop        | `name_en`/`name_ta` | `name`             |
| Farmer      | `created_by_employee` | `created_by`     |
| Visit       | `crop_health`     | `crop_condition`     |
| FieldCrop   | `land` (FK)       | `field` (FK)         |

---

## Postman Collections

| File | Purpose |
|------|---------|
| `docs/agri_admin.postman_collection.json` | Admin API (all modules) |
| `docs/agri_mobile.postman_collection.json` | Mobile / field officer API |
| `docs/agri_local_environment.json` | Environment variables for local dev |

Import all three into Postman. Set `district_id`, `village_id`, `crop_id` to valid IDs before running write operations.