"""Database / API environment diagnostics for farmer import troubleshooting."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client

from masters.models import Farmer

DEFAULT_QUARTER1_PATH = "imports/QUARTER 1GrpSum.xlsx"
DEFAULT_QUARTER2_PATH = "imports/QUARTER 2GrpSum.xlsx"


def resolve_quarter_path(raw: str, default: str) -> Path:
    """Resolve quarter Excel path relative to project BASE_DIR."""
    p = Path(raw or default)
    if not p.is_absolute():
        p = Path(settings.BASE_DIR) / p
    return p


def get_database_connection_info() -> dict[str, Any]:
    """Return active Django DB connection details."""
    db = settings.DATABASES["default"]
    db_url = getattr(settings, "DATABASE_URL", "") or os.getenv("DATABASE_URL", "")
    parsed_host = (urlsplit(db_url).hostname or "") if db_url else ""

    info: dict[str, Any] = {
        "engine": db.get("ENGINE", ""),
        "name": str(db.get("NAME", "")),
        "host": db.get("HOST") or parsed_host or "(local)",
        "port": db.get("PORT") or "",
        "user": db.get("USER") or "",
        "database_url_set": bool(db_url),
        "database_url_host": parsed_host or "(unset)",
        "app_env": os.getenv("APP_ENV", "local"),
        "settings_module": os.getenv("DJANGO_SETTINGS_MODULE", "config.settings"),
    }

    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("SELECT current_database()")
            info["current_database"] = cursor.fetchone()[0]
            try:
                cursor.execute("SELECT inet_server_addr()")
                row = cursor.fetchone()
                info["inet_server_addr"] = row[0] if row and row[0] else "(local socket)"
            except Exception as exc:
                info["inet_server_addr"] = f"(unavailable: {exc})"
        else:
            info["current_database"] = str(db.get("NAME", ""))
            info["inet_server_addr"] = "(non-postgresql)"

        for table in (
            "masters_farmer",
            "visits_visit",
            "masters_farmeractivity",
            "tracking_locationlog",
        ):
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                info[f"count_{table}"] = cursor.fetchone()[0]
            except Exception:
                info[f"count_{table}"] = -1

    info["orm_farmer_count"] = Farmer.objects.count()
    info["sample_farmers"] = list(
        Farmer.objects.order_by("id").values(
            "id", "name", "phone", "source_quarter", "source_file"
        )[:5]
    )
    return info


def resolve_quarter_paths(
    quarter1: str,
    quarter2: str,
    *,
    use_defaults: bool = True,
) -> dict[str, Any]:
    """Resolve quarter Excel paths and existence."""
    defaults = (DEFAULT_QUARTER1_PATH, DEFAULT_QUARTER2_PATH) if use_defaults else ("", "")
    out: dict[str, Any] = {}
    for key, raw, default in (
        ("quarter1", quarter1, defaults[0]),
        ("quarter2", quarter2, defaults[1]),
    ):
        p = resolve_quarter_path(raw, default) if (raw or default) else Path()
        if not raw and not default:
            out[key] = {"path": "", "exists": False, "parsed_farmers": 0}
            continue
        exists = p.exists()
        parsed = 0
        invalid_count = 0
        if exists:
            from farmers.farmer_quarter_import import parse_quarter_workbook

            farmers, invalid, _villages = parse_quarter_workbook(
                p, quarter_key=key
            )
            parsed = len(farmers)
            invalid_count = len(invalid)
        out[key] = {
            "path": str(p),
            "exists": exists,
            "parsed_farmers": parsed,
            "invalid_rows": invalid_count,
        }
    return out


def preview_import_summary(quarter1: str, quarter2: str) -> dict[str, Any]:
    """Dry-run import stats (duplicates, invalid rows) without DB writes."""
    from farmers.farmer_quarter_import import run_full_import

    q1 = resolve_quarter_path(quarter1, DEFAULT_QUARTER1_PATH)
    q2 = resolve_quarter_path(quarter2, DEFAULT_QUARTER2_PATH)
    if not q1.exists() and not q2.exists():
        return {"ready": False, "reason": "No Excel files found"}
    result = run_full_import(
        q1 if q1.exists() else None,
        q2 if q2.exists() else None,
        dry_run=True,
    )
    return {
        "ready": True,
        "quarter1_parsed": result.quarter1_rows_processed,
        "quarter2_parsed": result.quarter2_rows_processed,
        "farmers_created": result.farmers_created,
        "farmers_updated": result.farmers_updated,
        "duplicates_skipped": result.duplicates_skipped,
        "invalid_rows": result.invalid_rows,
        "village_count": result.village_count,
        "district": result.district,
    }


def probe_farmer_api_endpoints() -> dict[str, Any]:
    """Hit farmer list endpoints via Django test client (same process/DB as caller)."""
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()
    if admin is None:
        admin = User.objects.filter(is_staff=True).first()

    if admin is None:
        return {"error": "No admin/staff user for API probe"}

    client = Client()
    client.force_login(admin)

    endpoints = [
        "/api/v1/admin/farmers/",
        "/api/v1/farmers/",
        "/api/v1/masters/farmers/",
        "/api/v1/mobile/farmers/",
    ]

    results: dict[str, Any] = {}
    for path in endpoints:
        resp = client.get(path)
        count = None
        sample = []
        try:
            body = resp.json()
            if isinstance(body, dict):
                data = body.get("data", body)
                if isinstance(data, dict) and "count" in data:
                    count = data["count"]
                    rows = data.get("results") or []
                elif isinstance(data, dict) and "results" in data:
                    count = data.get("count", len(data["results"]))
                    rows = data["results"]
                elif isinstance(data, list):
                    count = len(data)
                    rows = data
                else:
                    rows = []
                for row in rows[:3]:
                    if isinstance(row, dict):
                        sample.append(
                            {
                                "id": row.get("id"),
                                "name": row.get("name"),
                                "source_quarter": row.get("source_quarter"),
                            }
                        )
        except Exception:
            pass
        results[path] = {
            "status": resp.status_code,
            "count": count,
            "sample": sample,
        }

    from api.admin.views import FarmerViewSet

    admin_qs = FarmerViewSet.queryset
    results["_admin_viewset"] = {
        "db_alias": "default",
        "queryset_count": admin_qs.count(),
        "sample": list(
            admin_qs.order_by("-created_at").values(
                "id", "name", "source_quarter"
            )[:5]
        ),
        "sql": str(admin_qs[:1].query),
    }
    return results
