#!/usr/bin/env python
"""
Backend API audit — compare DB counts vs API responses (read-only).

Usage (from project root):
  python scripts/audit_backend_apis.py
  python scripts/audit_backend_apis.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# Django setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.test import APIClient

from accounts.models import EmployeeProfile
from dashboard.services import get_stats
from masters.models import Crop, District, Farmer, ProblemCategory, ProblemMaster, Village
from masters.models import CropIssue, Recommendation, FarmerField
from tracking.models import LocationLog, WorkDay
from visits.models import Visit


@dataclass
class EndpointAudit:
    module: str
    endpoint: str
    serializer_hint: str
    pagination: str
    page_size_default: str
    supports_page_size: bool
    supports_all: bool
    search: str
    ordering: str
    response_pattern: str
    db_count: int | None
    api_count: int | None
    response_rows: int
    page_size_used: str
    status_code: int
    notes: list[str] = field(default_factory=list)
    mismatch: bool = False


def _extract_count(body: Any) -> tuple[int | None, int, str]:
    """Return (total_count, rows_in_page, pattern_label)."""
    if not isinstance(body, dict):
        if isinstance(body, list):
            return len(body), len(body), "raw_array"
        return None, 0, "unknown"

    # Pattern A: {success, data: [...]}
    if "success" in body and "data" in body:
        data = body["data"]
        if isinstance(data, list):
            return len(data), len(data), "A_flat_list"
        if isinstance(data, dict):
            if "count" in data:
                results = data.get("results") or []
                return int(data["count"]), len(results), "C_wrapped_paginated"
            if "total" in data:
                return int(data["total"]), 1, "A_stats_object"
            # stats object with nested counts
            for key in ("farmers", "total", "total_farmers"):
                if key in data and isinstance(data[key], (int, float)):
                    return int(data[key]), 1, "A_stats_scalar"
        return None, 0, "A_unknown_data"

    # Pattern B: DRF {count, results}
    if "count" in body and "results" in body:
        return int(body["count"]), len(body.get("results") or []), "B_drf_paginated"

    return None, 0, "unknown"


def _get(path: str, client: APIClient, params: dict | None = None) -> tuple[int, Any]:
    resp = client.get(path, params or {}, HTTP_HOST="localhost")
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(
        is_staff=True
    ).first()
    if not admin:
        print("ERROR: No admin user for API audit")
        return 1

    client = APIClient()
    client.force_authenticate(user=admin)

    # Known DB baseline
    db = {
        "farmers_active": Farmer.objects.filter(is_active=True).count(),
        "farmers_all": Farmer.objects.count(),
        "districts": District.objects.filter(is_active=True).count(),
        "villages": Village.objects.filter(is_active=True).count(),
        "crops_active": Crop.objects.filter(is_active=True).count(),
        "crops_all": Crop.objects.count(),
        "problem_masters_active": ProblemMaster.objects.filter(is_active=True).count(),
        "problem_masters_all": ProblemMaster.objects.count(),
        "problem_categories": ProblemCategory.objects.filter(is_active=True).count(),
        "visits": Visit.objects.count(),
        "crop_issues": CropIssue.objects.count(),
        "recommendations": Recommendation.objects.count(),
        "employees_active": EmployeeProfile.objects.filter(
            is_active_employee=True
        ).count(),
        "location_logs": LocationLog.objects.count(),
        "workdays": WorkDay.objects.count(),
        "farmer_fields": FarmerField.objects.filter(is_active=True).count(),
    }

    audits: list[EndpointAudit] = []

    def audit_list(
        module: str,
        path: str,
        db_count: int | None,
        serializer: str,
        pagination: str,
        page_default: str,
        page_size_param: bool,
        search_desc: str,
        ordering: str,
        params: dict | None = None,
        expected_db: int | None = None,
    ):
        params = params or {}
        status, body = _get(path, client, params)
        api_count, rows, pattern = _extract_count(body)
        compare = expected_db if expected_db is not None else db_count
        mismatch = (
            compare is not None
            and api_count is not None
            and int(api_count) != int(compare)
        )
        page_size = params.get("page_size", page_default)
        a = EndpointAudit(
            module=module,
            endpoint=path + (f"?{params}" if params else ""),
            serializer_hint=serializer,
            pagination=pagination,
            page_size_default=page_default,
            supports_page_size=page_size_param,
            supports_all=False,
            search=search_desc,
            ordering=ordering,
            response_pattern=pattern,
            db_count=compare,
            api_count=api_count,
            response_rows=rows,
            page_size_used=str(page_size),
            status_code=status,
            mismatch=mismatch,
        )
        if mismatch:
            a.notes.append(f"DB={compare} API count={api_count}")
        if api_count and rows and rows < api_count and pagination != "none":
            a.notes.append(
                f"Paginated: showing {rows} of {api_count} (count field OK)"
            )
        audits.append(a)
        print(
            f"[{'MISMATCH' if mismatch else 'OK' if status == 200 else 'ERR'}] "
            f"{path} | HTTP {status} | DB={compare} | API count={api_count} | "
            f"rows={rows} | pattern={pattern}"
        )

    print("=" * 72)
    print("DB BASELINE")
    print(json.dumps(db, indent=2))
    print("=" * 72)
    print("LIST API AUDITS")
    print("-" * 72)

    # Farmers
    audit_list(
        "Farmers",
        "/api/v1/farmers/",
        db["farmers_all"],
        "FarmerListSerializer",
        "PageNumberPagination",
        "20",
        True,
        "search (name, phone, code, village)",
        "name",
    )
    audit_list(
        "Farmers",
        "/api/v1/admin/farmers/",
        db["farmers_all"],
        "AdminFarmerSerializer",
        "AdminPagination",
        "50",
        True,
        "search_fields on ViewSet",
        "-created_at",
    )
    audit_list(
        "Farmers",
        "/api/v1/masters/farmers/",
        db["farmers_all"],
        "FarmerSerializer",
        "MasterPagination",
        "50",
        True,
        "search name, phone, farmer_code, village__name",
        "name",
    )

    # Locations
    audit_list(
        "Masters/Locations",
        "/api/v1/masters/districts/",
        db["districts"],
        "DistrictSerializer",
        "MasterPagination",
        "50",
        True,
        "search name",
        "name",
    )
    audit_list(
        "Masters/Locations",
        "/api/v1/masters/villages/",
        db["villages"],
        "VillageSerializer",
        "MasterPagination",
        "50",
        True,
        "search name; filter district, district_id",
        "name",
    )
    audit_list(
        "Masters/Locations",
        "/api/v1/masters/villages/",
        db["villages"],
        "VillageSerializer",
        "MasterPagination",
        "50",
        True,
        "page_size=500",
        "name",
        params={"page_size": 500},
    )

    # Crops
    audit_list(
        "Masters/Crops",
        "/api/v1/masters/crops/",
        db["crops_active"],
        "CropSerializer",
        "none",
        "all",
        False,
        "search name_en, name_ta",
        "name_en",
    )
    audit_list(
        "Masters/Crops",
        "/api/v1/crops/",
        db["crops_active"],
        "CropSerializer",
        "none",
        "all",
        False,
        "active only",
        "name_en",
    )
    audit_list(
        "Masters/Crops",
        "/api/v1/admin/crop-catalog/",
        db["crops_all"],
        "AdminCropSerializer",
        "AdminPagination",
        "50",
        True,
        "search name_en, name_ta",
        "name_en",
    )
    audit_list(
        "Farmers",
        "/api/v1/crop-catalog/",
        db["crops_active"],
        "CropMasterSerializer",
        "StandardPagination",
        "20",
        True,
        "search, crop_category",
        "name_en",
    )

    # Problem items
    audit_list(
        "Masters/Problem Items",
        "/api/v1/masters/problem-masters/",
        db["problem_masters_active"],
        "ProblemMasterSerializer",
        "none",
        "all",
        False,
        "category_id, category, crop_id",
        "category__name",
    )
    audit_list(
        "Masters/Problem Items",
        "/api/v1/admin/problem-masters/",
        db["problem_masters_active"],
        "ProblemMasterSerializer",
        "none (overridden)",
        "all",
        False,
        "category, crop_id filters",
        "category__name",
    )
    audit_list(
        "Masters/Problem Items",
        "/api/v1/problem-items/",
        db["problem_masters_active"],
        "ProblemItemSerializer",
        "ProblemItemPagination",
        "50",
        True,
        "category, crop_id, search",
        "category__name",
    )
    audit_list(
        "Masters/Problem Items",
        "/api/v1/admin/problem-items/",
        db["problem_masters_active"],
        "ProblemItemSerializer",
        "none (overridden)",
        "all",
        False,
        "category, crop_id",
        "category__name",
    )

    # Visits, issues, recommendations
    audit_list(
        "Visits",
        "/api/v1/visits/",
        db["visits"],
        "VisitSerializer",
        "VisitListPagination",
        "20",
        True,
        "search",
        "-created_at",
    )
    audit_list(
        "Visits",
        "/api/v1/admin/visits/",
        db["visits"],
        "AdminVisitSerializer",
        "AdminPagination",
        "50",
        True,
        "search_fields",
        "-created_at",
    )
    audit_list(
        "Crop Issues",
        "/api/v1/admin/issues/",
        db["crop_issues"],
        "AdminCropIssueSerializer",
        "AdminPagination",
        "50",
        True,
        "search, filterset",
        "-created_at",
    )
    audit_list(
        "Recommendations",
        "/api/v1/admin/recommendations/",
        db["recommendations"],
        "AdminRecommendationSerializer",
        "AdminPagination",
        "50",
        True,
        "search_fields",
        "-created_at",
    )

    # Employees
    audit_list(
        "Employees",
        "/api/v1/employees/",
        db["employees_active"],
        "AdminEmployeeListSerializer",
        "utils.StandardPagination",
        "50",
        True,
        "search, is_active, role",
        "name",
    )
    audit_list(
        "Employees",
        "/api/v1/employees/admin/employees/",
        db["employees_active"],
        "AdminEmployeeListSerializer",
        "inline PageNumberPagination",
        "20",
        True,
        "search, role, district_id",
        "name",
    )

    # Tracking
    audit_list(
        "Tracking",
        "/api/v1/tracking/workdays/history/",
        db["workdays"],
        "inline dict",
        "none (cap 90)",
        "90",
        False,
        "staff=all",
        "-started_at",
    )

    # Dashboard stats
    print("-" * 72)
    print("DASHBOARD / STATS")
    status, dash_body = _get("/api/v1/dashboard/", client)
    dash_stats = get_stats()
    api_dash = dash_body.get("data", {}) if isinstance(dash_body, dict) else {}
    dash_farmers_db = dash_stats.get("total_farmers")
    dash_farmers_api = api_dash.get("total_farmers")
    print(
        f"GET /api/v1/dashboard/ | farmers DB(selector)={dash_farmers_db} "
        f"API={dash_farmers_api} | visits DB={dash_stats.get('total_visits')} "
        f"API={api_dash.get('total_visits')}"
    )
    status2, admin_dash = _get("/api/v1/admin/dashboard/stats/", client)
    admin_data = admin_dash.get("data", {}) if isinstance(admin_dash, dict) else {}
    print(
        f"GET /api/v1/admin/dashboard/stats/ | farmers API={admin_data.get('farmers')} "
        f"(DB active farmers={db['farmers_active']}) visits API={admin_data.get('visits')}"
    )
    status3, farmer_stats = _get("/api/v1/farmers/stats/", client)
    fs_data = farmer_stats.get("data", {}) if isinstance(farmer_stats, dict) else {}
    print(
        f"GET /api/v1/farmers/stats/ | total API={fs_data.get('total')} "
        f"DB all farmers={db['farmers_all']}"
    )

    # Filter tests
    print("-" * 72)
    print("FILTER TESTS")
    sample_village = (
        Village.objects.filter(farmers__isnull=False).values_list("name", flat=True).first()
    )
    if sample_village:
        status, body = _get(
            "/api/v1/farmers/", client, {"village": sample_village, "page_size": 100}
        )
        cnt, rows, _ = _extract_count(body)
        db_v = Farmer.objects.filter(village__name__icontains=sample_village).count()
        print(
            f"Farmers ?village={sample_village!r} | DB={db_v} API count={cnt} rows={rows}"
        )

    status, body = _get("/api/v1/farmers/", client, {"search": "Kanagaraj", "page_size": 50})
    cnt, rows, _ = _extract_count(body)
    db_s = Farmer.objects.filter(
        Q(name__icontains="Kanagaraj")
        | Q(phone__icontains="Kanagaraj")
        | Q(farmer_code__icontains="Kanagaraj")
        | Q(village__name__icontains="Kanagaraj")
    ).count()
    print(f"Farmers ?search=Kanagaraj | DB={db_s} API count={cnt} rows={rows}")

    status, body = _get(
        "/api/v1/masters/problem-masters/", client, {"category": "pest"}
    )
    pest_cnt = len(body.get("data", [])) if isinstance(body.get("data"), list) else None
    db_pest = ProblemMaster.objects.filter(
        is_active=True, category__code="pest"
    ).count()
    print(
        f"Problem masters ?category=pest | DB={db_pest} API len(data)={pest_cnt}"
    )

    status, body = _get("/api/v1/problem-items/", client, {"category": "pest"})
    data = body.get("data", {}) if isinstance(body, dict) else {}
    api_pest = data.get("count") if isinstance(data, dict) else None
    print(f"Problem items ?category=pest | DB={db_pest} API count={api_pest}")

    # Reports
    print("-" * 72)
    print("REPORTS (aggregate lists)")
    for path in (
        "/api/v1/reports/employee-visits/",
        "/api/v1/reports/village-visits/",
        "/api/v1/reports/crop-problems/",
    ):
        status, body = _get(path, client)
        data = body.get("data", []) if isinstance(body, dict) else []
        print(f"{path} | HTTP {status} | rows={len(data) if isinstance(data, list) else 'n/a'}")

    mismatches = [a for a in audits if a.mismatch]
    errors = [a for a in audits if a.status_code != 200]

    report = {
        "db_counts": db,
        "audits": [a.__dict__ for a in audits],
        "mismatches": [a.__dict__ for a in mismatches],
        "http_errors": [a.__dict__ for a in errors],
        "dashboard": {
            "selector_total_farmers": dash_farmers_db,
            "api_dashboard_total_farmers": dash_farmers_api,
            "admin_stats_farmers": admin_data.get("farmers"),
        },
        "summary": {
            "endpoints_audited": len(audits),
            "mismatch_count": len(mismatches),
            "http_error_count": len(errors),
        },
    }

    print("=" * 72)
    print("SUMMARY")
    print(f"  Endpoints audited: {len(audits)}")
    print(f"  Count mismatches: {len(mismatches)}")
    print(f"  HTTP errors: {len(errors)}")
    if mismatches:
        print("  Mismatches:")
        for m in mismatches:
            print(f"    - {m.endpoint}: DB={m.db_count} API={m.api_count}")

    if args.json:
        print(json.dumps(report, indent=2, default=str))

    return 1 if mismatches or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
