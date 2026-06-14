#!/usr/bin/env python3
"""
Safe Render DB sync helper: backup local + Render, optional restore.

Usage:
  python scripts/render_db_sync.py audit
  python scripts/render_db_sync.py backup-local
  python scripts/render_db_sync.py backup-render
  python scripts/render_db_sync.py counts-local
  python scripts/render_db_sync.py counts-render
  python scripts/render_db_sync.py restore-render --backup-file backups/....dump
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import dj_database_url
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "backups"
PG_DUMP = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe")
PG_RESTORE = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
PSQL = Path(r"C:\Program Files\PostgreSQL\18\bin\psql.exe")
RENDER_SUFFIX = "singapore-postgres.render.com"


def _load_env(path: Path) -> dict:
    if not path.exists():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def _fix_render_host(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if host.startswith("dpg-") and "." not in host:
        host = f"{host}.{RENDER_SUFFIX}"
    username = quote(parsed.username or "", safe="")
    password = quote(parsed.password or "", safe="")
    auth = username
    if password:
        auth = f"{auth}:{password}"
    if auth:
        auth = f"{auth}@"
    port = parsed.port or 5432
    return urlunsplit((parsed.scheme, f"{auth}{host}:{port}", parsed.path, parsed.query, parsed.fragment))


def _db_cfg(source: str) -> dict:
    if source == "local":
        env = _load_env(ROOT / ".env")
        url = env.get("DATABASE_URL", "")
        if not url:
            raise SystemExit("Local DATABASE_URL missing in .env")
    else:
        env = _load_env(ROOT / "render.production.env")
        url = env.get("DATABASE_URL", "")
        if not url:
            raise SystemExit("Render DATABASE_URL missing in render.production.env")
        url = _fix_render_host(url)
    cfg = dj_database_url.parse(url)
    cfg["url"] = url
    return cfg


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _run(cmd: list[str], env: dict | None = None) -> None:
    print("RUN:", " ".join(cmd[:3]), "...")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        raise SystemExit(proc.returncode)


def backup_db(source: str) -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    cfg = _db_cfg(source)
    out = BACKUPS / f"{source}_{_stamp()}.dump"
    env = os.environ.copy()
    if cfg.get("PASSWORD"):
        env["PGPASSWORD"] = str(cfg["PASSWORD"])
    _run(
        [
            str(PG_DUMP),
            "-h",
            str(cfg["HOST"]),
            "-p",
            str(cfg.get("PORT") or 5432),
            "-U",
            str(cfg["USER"]),
            "-d",
            str(cfg["NAME"]),
            "-F",
            "c",
            "-f",
            str(out),
            "--no-owner",
            "--no-acl",
        ],
        env=env,
    )
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"OK backup {source}: {out} ({size_mb:.2f} MB)")
    return out


def counts(source: str) -> dict:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if source == "local":
        # default settings load .env
        pass
    else:
        cfg = _db_cfg("render")
        os.environ["APP_ENV"] = "production"
        os.environ["DATABASE_URL"] = cfg["url"]
        os.environ["RENDER_POSTGRES_HOST_SUFFIX"] = RENDER_SUFFIX
        os.environ.setdefault("SECRET_KEY", "audit-only-not-for-runtime")
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.contrib.auth.models import User
    from accounts.models import EmployeeProfile
    from masters.models import Farmer, Village, Crop, ProblemMaster
    from visits.models import Visit
    from tracking.models import LocationLog
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    applied = MigrationRecorder(connection).applied_migrations()
    has_0026 = any(
        app == "visits" and name == "0026_visit_recommendation" for app, name in applied
    )
    return {
        "users": User.objects.count(),
        "employees": EmployeeProfile.objects.count(),
        "farmers": Farmer.objects.count(),
        "villages": Village.objects.count(),
        "crops": Crop.objects.count(),
        "problem_items": ProblemMaster.objects.count(),
        "visits": Visit.objects.count(),
        "location_logs": LocationLog.objects.count(),
        "migration_0026_visit_recommendation": has_0026,
    }


def restore_render(backup_file: Path) -> None:
    if not backup_file.exists():
        raise SystemExit(f"Backup not found: {backup_file}")
    cfg = _db_cfg("render")
    env = os.environ.copy()
    if cfg.get("PASSWORD"):
        env["PGPASSWORD"] = str(cfg["PASSWORD"])
    # Drop and recreate public schema (destructive — backup required first).
    _run(
        [
            str(PSQL),
            "-h",
            str(cfg["HOST"]),
            "-p",
            str(cfg.get("PORT") or 5432),
            "-U",
            str(cfg["USER"]),
            "-d",
            str(cfg["NAME"]),
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO public;",
        ],
        env=env,
    )
    _run(
        [
            str(PG_RESTORE),
            "-h",
            str(cfg["HOST"]),
            "-p",
            str(cfg.get("PORT") or 5432),
            "-U",
            str(cfg["USER"]),
            "-d",
            str(cfg["NAME"]),
            "--no-owner",
            "--no-acl",
            str(backup_file),
        ],
        env=env,
    )
    print(f"OK restored {backup_file} -> Render")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "audit",
            "backup-local",
            "backup-render",
            "counts-local",
            "counts-render",
            "restore-render",
        ],
    )
    parser.add_argument("--backup-file", type=Path)
    args = parser.parse_args()

    if args.action == "audit":
        local = _db_cfg("local")
        render = _db_cfg("render")
        print("LOCAL", local["HOST"], local["NAME"], local["USER"])
        print("RENDER", render["HOST"], render["NAME"], render["USER"])
        print("RENDER_URL", "https://agri-clinic-backend.onrender.com")
        return

    if args.action == "backup-local":
        backup_db("local")
        return
    if args.action == "backup-render":
        backup_db("render")
        return
    if args.action == "counts-local":
        print(counts("local"))
        return
    if args.action == "counts-render":
        print(counts("render"))
        return
    if args.action == "restore-render":
        if not args.backup_file:
            raise SystemExit("--backup-file required")
        restore_render(args.backup_file)
        return


if __name__ == "__main__":
    main()
