"""
Generate Postman collections from actual backend URL/serializer scan.
Run: python scripts/_gen_postman.py
"""

import json
import uuid
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(BASE_DIR, "docs")


def uid():
    return str(uuid.uuid4())


def folder(name, items, description=""):
    f = {"name": name, "item": items}
    if description:
        f["description"] = description
    return f


def req(
    name,
    method,
    path,
    body=None,
    form_data=None,
    raw_url_params=None,
    description="",
    auth=True,
    test_script=None,
):
    header = []
    if body:
        header.append({"key": "Content-Type", "value": "application/json"})

    raw_url = "{{base_url}}" + path
    path_parts = [p for p in path.lstrip("/").split("/") if p]

    r = {
        "name": name,
        "request": {
            "method": method,
            "header": header,
            "url": {
                "raw": raw_url,
                "host": ["{{base_url}}"],
                "path": path_parts,
            },
        },
    }

    if auth:
        r["request"]["auth"] = {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
        }

    if body is not None:
        r["request"]["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2, ensure_ascii=False),
            "options": {"raw": {"language": "json"}},
        }

    if form_data is not None:
        r["request"]["header"] = []
        r["request"]["body"] = {
            "mode": "formdata",
            "formdata": [
                {
                    "key": k,
                    "value": v,
                    "type": t,
                    **({"src": ""} if t == "file" else {}),
                }
                for k, v, t in form_data
            ],
        }

    if description:
        r["request"]["description"] = description

    if test_script:
        r["event"] = [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": test_script,
                },
            }
        ]

    return r


# ─────────────────────────────────────────
# LOGIN TEST SCRIPT
# ─────────────────────────────────────────
LOGIN_TEST = [
    "if (pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    pm.environment.set('access_token', res.access);",
    "    pm.environment.set('refresh_token', res.refresh);",
    "    pm.test('Login successful', function() {",
    "        pm.expect(res.access).to.be.a('string');",
    "    });",
    "}",
]

MOBILE_LOGIN_TEST = [
    "if (pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var token = (res.data && res.data.access) || res.access;",
    "    pm.environment.set('mobile_access_token', token);",
    "    pm.environment.set('mobile_refresh_token', (res.data && res.data.refresh) || res.refresh);",
    "    pm.test('Mobile login successful', function() {",
    "        pm.expect(token).to.be.a('string');",
    "    });",
    "}",
]

CREATE_FARMER_TEST = [
    "if (pm.response.code === 201 || pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var id = (res.id) || (res.data && res.data.id);",
    "    if (id) pm.environment.set('farmer_id', id);",
    "}",
]

CREATE_VISIT_TEST = [
    "if (pm.response.code === 201 || pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var id = (res.data && res.data.visit_id) || (res.data && res.data.id) || res.id;",
    "    if (id) pm.environment.set('visit_id', id);",
    "}",
]

CREATE_EMP_TEST = [
    "if (pm.response.code === 201 || pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var id = (res.data && res.data.id) || res.id;",
    "    if (id) pm.environment.set('employee_id', id);",
    "}",
]

CREATE_DISTRICT_TEST = [
    "if (pm.response.code === 201 || pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var id = res.id || (res.data && res.data.id);",
    "    if (id) pm.environment.set('district_id', id);",
    "}",
]

CREATE_VILLAGE_TEST = [
    "if (pm.response.code === 201 || pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var id = res.id || (res.data && res.data.id);",
    "    if (id) pm.environment.set('village_id', id);",
    "}",
]

CREATE_CROP_TEST = [
    "if (pm.response.code === 201 || pm.response.code === 200) {",
    "    var res = pm.response.json();",
    "    var id = res.id || (res.data && res.data.id);",
    "    if (id) pm.environment.set('crop_id', id);",
    "}",
]


# ══════════════════════════════════════════════════
# ADMIN COLLECTION
# ══════════════════════════════════════════════════


def build_admin_collection():
    auth_folder = folder(
        "01 Auth",
        [
            req(
                "Login",
                "POST",
                "/auth/login/",
                body={"username": "admin", "password": "admin123"},
                auth=False,
                test_script=LOGIN_TEST,
                description="Authenticate as admin. Saves access_token + refresh_token to environment.",
            ),
            req(
                "Refresh Token",
                "POST",
                "/auth/refresh/",
                body={"refresh": "{{refresh_token}}"},
                auth=False,
                description="Get a new access token using refresh token.",
            ),
            req(
                "Logout",
                "POST",
                "/auth/logout/",
                body={"refresh": "{{refresh_token}}"},
                description="Blacklist the refresh token.",
            ),
            req("Me (Admin Profile)", "GET", "/employees/me/"),
        ],
    )

    emp_folder = folder(
        "02 Employees",
        [
            req(
                "Create Employee",
                "POST",
                "/employees/create/",
                body={
                    "username": "john_field",
                    "password": "Field@12345",
                    "phone": "9876543210",
                },
                test_script=CREATE_EMP_TEST,
                description="Admin creates a new field employee. Role is always FieldAgent.",
            ),
            req("List Employees", "GET", "/employees/"),
            req("Get Employee", "GET", "/employees/{{employee_id}}/"),
            req(
                "Update Employee",
                "PUT",
                "/employees/{{employee_id}}/",
                body={"username": "john_field_updated", "phone": "9876543211"},
            ),
            req(
                "Toggle Employee Status",
                "POST",
                "/employees/{{employee_id}}/toggle/",
                description="Activate or deactivate an employee.",
            ),
            req("Admin — List/Create Employees", "GET", "/employees/admin/employees/"),
            req(
                "Admin — Employee Detail",
                "GET",
                "/employees/admin/employees/{{employee_id}}/",
            ),
            req(
                "Admin — Update Employee",
                "PUT",
                "/employees/admin/employees/{{employee_id}}/",
                body={"phone": "9876543299"},
            ),
            req(
                "Admin — Toggle Status",
                "POST",
                "/employees/admin/employees/{{employee_id}}/toggle-status/",
            ),
            req(
                "Admin — Reset Password",
                "POST",
                "/employees/admin/reset-password/",
                body={"user_id": "{{employee_id}}", "new_password": "NewPass@123"},
                description="Admin resets an employee's password.",
            ),
            req(
                "Create Admin User",
                "POST",
                "/employees/create-admin/",
                body={
                    "username": "new_admin",
                    "password": "Admin@1234",
                    "phone": "9000000001",
                },
            ),
        ],
    )

    masters_folder = folder(
        "03 Masters (Districts / Villages / Crops)",
        [
            req("List Districts", "GET", "/masters/districts/"),
            req(
                "Create District",
                "POST",
                "/masters/districts/",
                body={"name": "Viluppuram"},
                test_script=CREATE_DISTRICT_TEST,
            ),
            req("Get District", "GET", "/masters/districts/{{district_id}}/"),
            req(
                "Update District",
                "PUT",
                "/masters/districts/{{district_id}}/",
                body={"name": "Viluppuram Updated"},
            ),
            req(
                "Delete (Soft) District",
                "DELETE",
                "/masters/districts/{{district_id}}/",
            ),
            req(
                "Restore District",
                "POST",
                "/masters/districts/{{district_id}}/restore/",
            ),
            req("List Villages", "GET", "/masters/villages/"),
            req(
                "List Villages by District",
                "GET",
                "/masters/villages/?district={{district_id}}",
            ),
            req(
                "Create Village",
                "POST",
                "/masters/villages/",
                body={"name": "Lalgudi", "district": "{{district_id}}"},
                test_script=CREATE_VILLAGE_TEST,
            ),
            req("Get Village", "GET", "/masters/villages/{{village_id}}/"),
            req("List Crops", "GET", "/masters/crops/"),
            req(
                "Create Crop",
                "POST",
                "/masters/crops/",
                body={
                    "name_en": "Paddy",
                    "name_ta": "\u0ba8\u0bc6\u0bb2\u0bcd",
                    "scientific_name": "Oryza sativa",
                    "crop_category": "cereal",
                    "typical_season": "kharif",
                },
                test_script=CREATE_CROP_TEST,
                description="IMPORTANT: Use name_en and name_ta — NOT 'name'.",
            ),
            req("Get Crop", "GET", "/masters/crops/{{crop_id}}/"),
            req(
                "Update Crop",
                "PUT",
                "/masters/crops/{{crop_id}}/",
                body={
                    "name_en": "Paddy Updated",
                    "name_ta": "\u0ba8\u0bc6\u0bb2\u0bcd",
                    "crop_category": "cereal",
                    "typical_season": "kharif",
                },
            ),
            req("Delete (Soft) Crop", "DELETE", "/masters/crops/{{crop_id}}/"),
            req("Restore Crop", "POST", "/masters/crops/{{crop_id}}/restore/"),
            req("List Lands (FarmerField)", "GET", "/masters/lands/"),
            req("List Field Crops", "GET", "/masters/field-crops/"),
            req(
                "Admin — List Crop Catalog",
                "GET",
                "/admin/crop-catalog/",
                description="Flat crop catalog from admin router.",
            ),
            req(
                "Admin — Create Crop Catalog",
                "POST",
                "/admin/crop-catalog/",
                body={
                    "name_en": "Sugarcane",
                    "name_ta": "\u0b95\u0bb0\u0bc1\u0bae\u0bcd\u0baa\u0bc1",
                    "scientific_name": "Saccharum officinarum",
                    "crop_category": "commercial",
                    "typical_season": "annual",
                },
            ),
        ],
    )

    farmer_folder = folder(
        "04 Farmers",
        [
            req(
                "Create Farmer",
                "POST",
                "/farmers/",
                body={
                    "name": "Ravi Kumar",
                    "phone": "9876543210",
                    "district": "{{district_id}}",
                    "village": "{{village_id}}",
                    "address": "12, Main Street, Lalgudi",
                    "gps_location": "11.9416,79.3193",
                    "total_land_area": "3.50",
                    "irrigation_type": "borewell",
                    "soil_type": "red",
                    "assigned_employee": "{{employee_id}}",
                },
                test_script=CREATE_FARMER_TEST,
                description="Create farmer via masters router. district + village are FK IDs.",
            ),
            req("List Farmers (Masters)", "GET", "/masters/farmers/"),
            req("List Farmers (API)", "GET", "/farmers/"),
            req("Get Farmer (API)", "GET", "/farmers/{{farmer_id}}/"),
            req(
                "Update Farmer",
                "PUT",
                "/farmers/{{farmer_id}}/",
                body={
                    "name": "Ravi Kumar Updated",
                    "phone": "9876543210",
                    "district": "{{district_id}}",
                    "village": "{{village_id}}",
                    "total_land_area": "4.00",
                    "irrigation_type": "canal",
                },
            ),
            req("Delete (Soft) Farmer", "DELETE", "/farmers/{{farmer_id}}/"),
            req("Restore Farmer", "POST", "/masters/farmers/{{farmer_id}}/restore/"),
            req("Farmer Visits", "GET", "/farmers/{{farmer_id}}/visits/"),
            req("Farmer Activity Timeline", "GET", "/farmers/{{farmer_id}}/activity/"),
            req("Farmer Fields List", "GET", "/farmers/{{farmer_id}}/fields/"),
            req(
                "Create Farmer Field",
                "POST",
                "/farmers/{{farmer_id}}/fields/",
                body={
                    "land_name": "North Plot",
                    "land_area": 1.5,
                    "land_type": "dry",
                    "soil_type": "red",
                    "gps_location": "11.9416,79.3193",
                },
            ),
            req(
                "Add Crop to Field",
                "POST",
                "/fields/{{field_id}}/crops/",
                body={
                    "crop": "{{crop_id}}",
                    "season": "kharif",
                    "sowing_date": "2026-06-01",
                    "expected_harvest": "2026-10-01",
                    "area": 1.0,
                },
            ),
            req("Admin — List Farmers", "GET", "/admin/farmers/"),
            req("Admin — Farmer Detail", "GET", "/admin/farmers/{{farmer_id}}/"),
            req("Admin — Farmer Fields", "GET", "/admin/fields/"),
        ],
    )

    visit_folder = folder(
        "05 Visits",
        [
            req(
                "Create Visit",
                "POST",
                "/visits/",
                body={
                    "farmer_name": "Ravi Kumar",
                    "farmer_phone": "9876543210",
                    "district": "{{district_id}}",
                    "village": "{{village_id}}",
                    "visit_date": "2026-04-09",
                    "land_name": "North Plot",
                    "land_area": 1.5,
                    "crop": "{{crop_id}}",
                    "crop_stage": "vegetative",
                    "variety": "ADT 43",
                    "season": "kharif",
                    "sowing_date": "2026-02-01",
                    "crop_health": "good",
                    "pest_issue": False,
                    "disease_issue": False,
                    "weed_condition": "low",
                    "notes": "Crop looks healthy. Recommended fertilizer.",
                    "fertilizer_advice": "Apply urea 20kg/acre",
                    "pesticide_advice": "",
                    "irrigation_advice": "Ensure proper drainage",
                    "follow_up_required": True,
                    "next_visit_date": "2026-04-23",
                    "latitude": 11.9416,
                    "longitude": 79.3193,
                },
                test_script=CREATE_VISIT_TEST,
                description="Create a visit record. Admin may omit latitude/longitude.",
            ),
            req("List Visits", "GET", "/visits/"),
            req("Get Visit Detail", "GET", "/visits/{{visit_id}}/"),
            req(
                "Update Visit (PATCH)",
                "PATCH",
                "/visits/{{visit_id}}/",
                body={
                    "notes": "Updated observation — disease spreading to 20% area.",
                    "disease_issue": True,
                    "follow_up_required": True,
                },
            ),
            req("Complete Visit", "POST", "/visits/{{visit_id}}/complete/"),
            req("Visit Stats", "GET", "/visits/stats/"),
            req(
                "Bulk Visit Upload",
                "POST",
                "/visits/bulk/",
                body={
                    "visits": [
                        {
                            "farmer_name": "Farmer A",
                            "farmer_phone": "9000000001",
                            "district": "{{district_id}}",
                            "village": "{{village_id}}",
                            "visit_date": "2026-04-09",
                            "latitude": 11.9416,
                            "longitude": 79.3193,
                            "notes": "Bulk upload test",
                        }
                    ]
                },
            ),
            req("Admin — List Visits", "GET", "/admin/visits/"),
            req("Admin — Visit Detail", "GET", "/admin/visits/{{visit_id}}/"),
        ],
    )

    media_folder = folder(
        "06 Visit Media & Attachments",
        [
            req(
                "Upload Visit Media (multipart)",
                "POST",
                "/visits/{{visit_id}}/upload-media/",
                form_data=[
                    ("file", "", "file"),
                    ("media_type", "image", "text"),
                    ("caption", "Leaf damage observed on lower leaves", "text"),
                ],
                description="Upload image/bill/audio/video. media_type: image | bill | audio | video",
            ),
            req(
                "Upload Attachment (multipart)",
                "POST",
                "/visits/{{visit_id}}/attachments/",
                form_data=[
                    ("file", "", "file"),
                    ("file_type", "CROP", "text"),
                ],
                description="file_type: CROP | SOIL | BILL | VOICE | PDF | OTHER",
            ),
            req(
                "Upload Photo (quick)",
                "POST",
                "/visits/upload-photo/",
                form_data=[
                    ("photo", "", "file"),
                    ("visit_id", "{{visit_id}}", "text"),
                ],
            ),
            req(
                "Create Crop Issue",
                "POST",
                "/visits/{{visit_id}}/issues/",
                body={
                    "crop": "{{crop_id}}",
                    "severity": "moderate",
                    "description": "Aphid infestation on 30% of plants",
                    "recommendations": [
                        {"action": "spray_imidacloprid", "notes": "Apply 0.5ml/L water"}
                    ],
                },
                description="severity choices: low | moderate | high | critical",
            ),
            req("List All Issues", "GET", "/issues/"),
            req("Admin — List Issues", "GET", "/admin/issues/"),
            req("Admin — Issue Detail", "GET", "/admin/issues/{{issue_id}}/"),
            req(
                "Create Recommendation",
                "POST",
                "/issues/{{issue_id}}/recommendations/",
                body={
                    "action": "spray_imidacloprid",
                    "notes": "Apply 0.5ml/L water, spray in early morning",
                },
            ),
            req("Admin — List Recommendations", "GET", "/admin/recommendations/"),
        ],
    )

    tracking_folder = folder(
        "07 Tracking",
        [
            req(
                "Start Workday",
                "POST",
                "/tracking/workday/start/",
                body={},
                description="Employee starts their workday. Creates a WorkDay record.",
            ),
            req("End Workday", "POST", "/tracking/workday/end/", body={}),
            req("Current Workday", "GET", "/tracking/workday/current/"),
            req("Workday History", "GET", "/tracking/workdays/history/"),
            req(
                "Push Location",
                "POST",
                "/tracking/location/push/",
                body={
                    "latitude": 11.9416,
                    "longitude": 79.3193,
                    "accuracy": 8.5,
                    "battery_level": 75,
                    "network_type": "4G",
                    "device_model": "Samsung Galaxy A52",
                    "app_version": "1.0.0",
                },
                description="Push a single GPS location. Requires active workday.",
            ),
            req(
                "Bulk Location Upload",
                "POST",
                "/tracking/location/bulk/",
                body={
                    "locations": [
                        {
                            "latitude": 11.9416,
                            "longitude": 79.3193,
                            "recorded_at": "2026-04-09T09:00:00Z",
                            "accuracy": 10.0,
                            "battery_level": 80,
                        },
                        {
                            "latitude": 11.9420,
                            "longitude": 79.3200,
                            "recorded_at": "2026-04-09T09:05:00Z",
                            "accuracy": 8.0,
                            "battery_level": 79,
                        },
                    ]
                },
                description="Upload cached locations in batch.",
            ),
            req("Heartbeat", "POST", "/tracking/heartbeat/", body={}),
            req(
                "Workday Locations",
                "GET",
                "/tracking/workday/{{workday_id}}/locations/",
            ),
            req("Availability Events", "GET", "/tracking/availability/events/"),
            req("Employee Stats", "GET", "/tracking/employee-stats/"),
            req("Admin — All Employee Status", "GET", "/tracking/admin/status/"),
            req(
                "Admin — Dashboard Stats",
                "GET",
                "/tracking/admin/dashboard-stats/?date=2026-04-09",
            ),
            req("Admin — Employee GeoJSON", "GET", "/tracking/admin/geo/employees/"),
            req(
                "Admin — Employee Summary",
                "GET",
                "/tracking/admin/employee/{{employee_id}}/summary/?date=2026-04-09",
            ),
            req(
                "Admin — Employee Route",
                "GET",
                "/tracking/admin/employee/{{employee_id}}/route/?date=2026-04-09",
            ),
            req(
                "Admin — Employee Activity",
                "GET",
                "/tracking/admin/employee/{{employee_id}}/activity/",
            ),
            req(
                "Admin — Route GeoJSON",
                "GET",
                "/tracking/admin/geo/routes/{{employee_id}}/?date=2026-04-09",
            ),
            req(
                "Admin — Last Location",
                "GET",
                "/tracking/admin/geo/last_location/{{employee_id}}/",
            ),
            req("Work Start (alias)", "POST", "/work/start/", body={}),
            req("Work Stop (alias)", "POST", "/work/stop/", body={}),
        ],
    )

    dashboard_folder = folder(
        "08 Dashboard",
        [
            req("Dashboard Root", "GET", "/dashboard/"),
            req("Dashboard Summary", "GET", "/dashboard/summary/"),
            req("Visit Trends (30 days)", "GET", "/dashboard/visit-trends/?days=30"),
            req(
                "Employee Performance (30 days)",
                "GET",
                "/dashboard/employee-performance/?days=30",
            ),
            req(
                "Village Heatmap (Top 10)", "GET", "/dashboard/village-heatmap/?top=10"
            ),
            req("Admin Dashboard Stats", "GET", "/admin/dashboard/stats/"),
            req("Map — Farmers GeoJSON", "GET", "/map/farmers/"),
        ],
    )

    reports_folder = folder(
        "09 Reports",
        [
            req(
                "Employee Visit Report",
                "GET",
                "/reports/employee-visits/?start_date=2026-04-01&end_date=2026-04-09",
            ),
            req(
                "Village Visit Report",
                "GET",
                "/reports/village-visits/?start_date=2026-04-01&end_date=2026-04-09",
            ),
            req(
                "Crop Problem Report",
                "GET",
                "/reports/crop-problems/?start_date=2026-04-01&end_date=2026-04-09",
            ),
            req("Daily Report", "GET", "/reports/daily/?date=2026-04-09"),
            req("Monthly Report", "GET", "/reports/monthly/?month=4&year=2026"),
        ],
    )

    notif_folder = folder(
        "10 Notifications",
        [
            req("List Notifications", "GET", "/notifications/"),
            req("Unread Count", "GET", "/notifications/unread-count/"),
            req("Mark All Read", "POST", "/notifications/mark-all-read/", body={}),
            req(
                "Mark Single Read",
                "POST",
                "/notifications/{{notification_id}}/read/",
                body={},
            ),
        ],
    )

    audit_folder = folder(
        "11 Audit Logs",
        [
            req("List Audit Logs", "GET", "/audit/logs/"),
            req("Filter by User", "GET", "/audit/logs/?user={{employee_id}}"),
        ],
    )

    system_folder = folder(
        "12 System Settings",
        [
            req("Get Settings", "GET", "/system/settings/"),
            req("Get Config", "GET", "/system/config/"),
        ],
    )

    return {
        "info": {
            "_postman_id": uid(),
            "name": "Agri Clinic — Admin API (v2)",
            "description": (
                "Complete admin API collection. Import with agri_local_environment.json.\n\n"
                "Flow:\n"
                "1. Run 'Login' — access_token is auto-saved.\n"
                "2. Create District → Village → Crop.\n"
                "3. Create Employee, Create Farmer, then Visits."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            auth_folder,
            emp_folder,
            masters_folder,
            farmer_folder,
            visit_folder,
            media_folder,
            tracking_folder,
            dashboard_folder,
            reports_folder,
            notif_folder,
            audit_folder,
            system_folder,
        ],
    }


# ══════════════════════════════════════════════════
# MOBILE COLLECTION
# ══════════════════════════════════════════════════


def build_mobile_collection():
    def mreq(
        name, method, path, body=None, form_data=None, description="", test_script=None
    ):
        r = req(
            name,
            method,
            path,
            body=body,
            form_data=form_data,
            description=description,
            auth=True,
            test_script=test_script,
        )
        # Override auth to use mobile_access_token
        r["request"]["auth"] = {
            "type": "bearer",
            "bearer": [
                {"key": "token", "value": "{{mobile_access_token}}", "type": "string"}
            ],
        }
        return r

    auth_folder = folder(
        "01 Auth",
        [
            req(
                "Mobile Login",
                "POST",
                "/mobile/auth/login/",
                body={"username": "{{employee_username}}", "password": "Field@12345"},
                auth=False,
                test_script=MOBILE_LOGIN_TEST,
                description="Login as field employee. Saves mobile_access_token.",
            ),
            req(
                "Mobile Refresh Token",
                "POST",
                "/mobile/auth/refresh/",
                body={"refresh": "{{mobile_refresh_token}}"},
                auth=False,
            ),
            mreq(
                "Mobile Me",
                "GET",
                "/mobile/auth/me/",
                description="Get logged-in employee profile.",
            ),
        ],
    )

    work_folder = folder(
        "02 Work Session",
        [
            mreq(
                "Start Workday",
                "POST",
                "/mobile/work/start/",
                body={},
                description="Begin employee workday. Records start_time.",
            ),
            mreq("Work Status", "GET", "/mobile/work/status/"),
            mreq("Stop Workday", "POST", "/mobile/work/stop/", body={}),
            mreq(
                "Start Workday (Tracking alias)",
                "POST",
                "/tracking/workday/start/",
                body={},
            ),
            mreq(
                "End Workday (Tracking alias)",
                "POST",
                "/tracking/workday/end/",
                body={},
            ),
            mreq("Current Workday", "GET", "/tracking/workday/current/"),
        ],
    )

    tracking_folder = folder(
        "03 Location Tracking",
        [
            mreq(
                "Push Location",
                "POST",
                "/tracking/location/push/",
                body={
                    "latitude": 11.9416,
                    "longitude": 79.3193,
                    "accuracy": 8.5,
                    "battery_level": 75,
                    "network_type": "4G",
                    "device_model": "Samsung Galaxy A52",
                    "app_version": "1.0.0",
                },
                description="Push GPS location. Requires active workday.",
            ),
            mreq(
                "Mobile Tracking (alt endpoint)",
                "POST",
                "/mobile/tracking/",
                body={
                    "latitude": 11.9416,
                    "longitude": 79.3193,
                    "accuracy": 8.5,
                    "battery_level": 75,
                },
            ),
            mreq(
                "Bulk Location Upload",
                "POST",
                "/tracking/location/bulk/",
                body={
                    "locations": [
                        {
                            "latitude": 11.9416,
                            "longitude": 79.3193,
                            "recorded_at": "2026-04-09T09:00:00Z",
                            "accuracy": 10.0,
                            "battery_level": 80,
                        },
                        {
                            "latitude": 11.9420,
                            "longitude": 79.3200,
                            "recorded_at": "2026-04-09T09:05:00Z",
                            "accuracy": 8.0,
                            "battery_level": 79,
                        },
                    ]
                },
                description="Flush cached offline locations.",
            ),
            mreq("Heartbeat", "POST", "/tracking/heartbeat/", body={}),
            mreq(
                "Workday History",
                "GET",
                "/tracking/workdays/history/",
                description="Get employee workday history.",
            ),
        ],
    )

    visit_folder = folder(
        "04 Visits",
        [
            mreq(
                "Create Visit",
                "POST",
                "/mobile/visits/",
                body={
                    "farmer_name": "Ravi Kumar",
                    "farmer_phone": "9876543210",
                    "district": "{{district_id}}",
                    "village": "{{village_id}}",
                    "visit_date": "2026-04-09",
                    "land_name": "North Plot",
                    "land_area": 1.5,
                    "crop": "{{crop_id}}",
                    "crop_stage": "vegetative",
                    "variety": "ADT 43",
                    "season": "kharif",
                    "sowing_date": "2026-02-01",
                    "crop_health": "good",
                    "pest_issue": False,
                    "disease_issue": False,
                    "weed_condition": "low",
                    "notes": "Field visit — crop healthy",
                    "follow_up_required": False,
                    "latitude": 11.9416,
                    "longitude": 79.3193,
                },
                test_script=CREATE_VISIT_TEST,
                description="Create a visit. latitude/longitude required for employees.",
            ),
            mreq(
                "Create Visit (with media files)",
                "POST",
                "/mobile/visits/",
                form_data=[
                    ("farmer_name", "Ravi Kumar", "text"),
                    ("farmer_phone", "9876543210", "text"),
                    ("district", "{{district_id}}", "text"),
                    ("village", "{{village_id}}", "text"),
                    ("visit_date", "2026-04-09", "text"),
                    ("crop", "{{crop_id}}", "text"),
                    ("crop_health", "good", "text"),
                    ("notes", "Multipart visit with photo", "text"),
                    ("latitude", "11.9416", "text"),
                    ("longitude", "79.3193", "text"),
                    ("media", "", "file"),
                    ("media_type", "image", "text"),
                ],
                description="Create visit + attach media in single multipart request.",
            ),
            mreq("List My Visits", "GET", "/mobile/visits/?page=1&page_size=10"),
            mreq("Visit Stats", "GET", "/mobile/visits/stats/"),
        ],
    )

    media_folder = folder(
        "05 Media Upload",
        [
            mreq(
                "Upload Visit Media",
                "POST",
                "/visits/{{visit_id}}/upload-media/",
                form_data=[
                    ("file", "", "file"),
                    ("media_type", "image", "text"),
                    ("caption", "Leaf damage observed on lower leaves", "text"),
                ],
                description="media_type choices: image | bill | audio | video. caption is optional.",
            ),
            mreq(
                "Upload Attachment",
                "POST",
                "/visits/{{visit_id}}/attachments/",
                form_data=[
                    ("file", "", "file"),
                    ("file_type", "CROP", "text"),
                ],
                description="file_type choices: CROP | SOIL | BILL | VOICE | PDF | OTHER",
            ),
            mreq(
                "Upload Photo (quick upload)",
                "POST",
                "/visits/upload-photo/",
                form_data=[
                    ("photo", "", "file"),
                    ("visit_id", "{{visit_id}}", "text"),
                ],
            ),
        ],
    )

    dashboard_folder = folder(
        "06 Dashboard & Reports",
        [
            mreq("Mobile Dashboard", "GET", "/mobile/dashboard/"),
            mreq("Mobile Reports", "GET", "/mobile/reports/"),
            mreq("Mobile Visit Stats", "GET", "/mobile/visits/stats/"),
        ],
    )

    return {
        "info": {
            "_postman_id": uid(),
            "name": "Agri Clinic — Mobile API (v2)",
            "description": (
                "Mobile (employee) API collection. Import with agri_local_environment.json.\n\n"
                "Flow:\n"
                "1. Mobile Login — mobile_access_token saved.\n"
                "2. Start Workday.\n"
                "3. Push Location.\n"
                "4. Create Visit (with or without media).\n"
                "5. Upload Media separately if needed.\n"
                "6. End Workday."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            auth_folder,
            work_folder,
            tracking_folder,
            visit_folder,
            media_folder,
            dashboard_folder,
        ],
    }


# ══════════════════════════════════════════════════
# ENVIRONMENT
# ══════════════════════════════════════════════════


def build_environment():
    def ev(key, value, enabled=True):
        return {
            "id": uid(),
            "key": key,
            "value": value,
            "enabled": enabled,
            "type": "default",
        }

    return {
        "id": uid(),
        "name": "Agri Clinic — Local",
        "values": [
            ev("base_url", "http://127.0.0.1:8000/api/v1"),
            ev("access_token", ""),
            ev("refresh_token", ""),
            ev("mobile_access_token", ""),
            ev("mobile_refresh_token", ""),
            ev("employee_username", "emp_test"),
            ev("employee_id", ""),
            ev("district_id", ""),
            ev("village_id", ""),
            ev("crop_id", ""),
            ev("farmer_id", ""),
            ev("visit_id", ""),
            ev("field_id", ""),
            ev("issue_id", ""),
            ev("notification_id", ""),
            ev("workday_id", ""),
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": "2026-04-09T00:00:00.000Z",
        "_postman_exported_using": "Agri Clinic Backend Generator v2",
    }


# ══════════════════════════════════════════════════
# WRITE FILES
# ══════════════════════════════════════════════════

if __name__ == "__main__":
    os.makedirs(DOCS_DIR, exist_ok=True)

    admin_col = build_admin_collection()
    mobile_col = build_mobile_collection()
    env = build_environment()

    admin_path = os.path.join(DOCS_DIR, "agri_admin.postman_collection.json")
    mobile_path = os.path.join(DOCS_DIR, "agri_mobile.postman_collection.json")
    env_path = os.path.join(DOCS_DIR, "agri_local_environment.json")

    with open(admin_path, "w", encoding="utf-8") as f:
        json.dump(admin_col, f, indent=2, ensure_ascii=False)

    with open(mobile_path, "w", encoding="utf-8") as f:
        json.dump(mobile_col, f, indent=2, ensure_ascii=False)

    with open(env_path, "w", encoding="utf-8") as f:
        json.dump(env, f, indent=2, ensure_ascii=False)

    print(f"[OK] Admin collection  → {admin_path}")
    print(f"[OK] Mobile collection → {mobile_path}")
    print(f"[OK] Environment       → {env_path}")

    # Count requests
    def count_requests(col):
        def _count(items):
            c = 0
            for item in items:
                if "item" in item:
                    c += _count(item["item"])
                else:
                    c += 1
            return c

        return _count(col["item"])

    print(f"\n  Admin  requests: {count_requests(admin_col)}")
    print(f"  Mobile requests: {count_requests(mobile_col)}")
    print(f"  Env variables : {len(env['values'])}")
