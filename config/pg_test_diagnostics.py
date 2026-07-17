"""PostgreSQL session diagnostics for CI test database teardown."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from django.conf import settings

logger = logging.getLogger(__name__)

SESSION_DIAGNOSTIC_SQL = """
SELECT
    pid,
    usename,
    application_name,
    client_addr::text,
    backend_start,
    state,
    wait_event_type,
    wait_event,
    query_start,
    LEFT(query, 300) AS query
FROM pg_stat_activity
WHERE datname = %s
  AND pid <> pg_backend_pid()
ORDER BY backend_start
"""


def sanitize_pg_identifier(name: str) -> str:
    import re

    safe = re.sub(r"[^a-zA-Z0-9_]", "_", (name or "").strip())
    return safe[:63]


def resolve_test_database_name(explicit: str | None = None) -> str:
    if explicit:
        return sanitize_pg_identifier(explicit)
    test_settings = settings.DATABASES.get("default", {}).get("TEST", {})
    configured = test_settings.get("NAME")
    if configured:
        return sanitize_pg_identifier(str(configured))
    db_name = settings.DATABASES.get("default", {}).get("NAME", "")
    if isinstance(db_name, (str, bytes)):
        base = str(db_name)
    else:
        base = getattr(db_name, "name", str(db_name))
    return sanitize_pg_identifier(f"test_{base}")


def _connection_params() -> dict[str, Any]:
    default = settings.DATABASES["default"]
    return {
        "dbname": "postgres",
        "user": default.get("USER", ""),
        "password": default.get("PASSWORD", ""),
        "host": default.get("HOST", "") or "localhost",
        "port": int(default.get("PORT", 5432) or 5432),
        "connect_timeout": int(default.get("OPTIONS", {}).get("connect_timeout", 10)),
    }


@contextmanager
def _maintenance_cursor() -> Iterator[Any]:
    import psycopg2

    conn = psycopg2.connect(**_connection_params())
    try:
        with conn.cursor() as cursor:
            yield cursor
        conn.commit()
    finally:
        conn.close()


def fetch_test_db_sessions(db_name: str) -> list[dict[str, Any]]:
    with _maintenance_cursor() as cursor:
        cursor.execute(SESSION_DIAGNOSTIC_SQL, [db_name])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def count_test_db_sessions(db_name: str) -> int:
    with _maintenance_cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
            """,
            [db_name],
        )
        return int(cursor.fetchone()[0])


def log_test_db_sessions(db_name: str, *, phase: str) -> list[dict[str, Any]]:
    sessions = fetch_test_db_sessions(db_name)
    logger.info(
        "pg_stat_activity phase=%s database=%s session_count=%d",
        phase,
        db_name,
        len(sessions),
    )
    for session in sessions:
        logger.info(
            "pg_stat_activity phase=%s pid=%s user=%s app=%s addr=%s "
            "state=%s wait=%s/%s backend_start=%s query_start=%s query=%r",
            phase,
            session.get("pid"),
            session.get("usename"),
            session.get("application_name"),
            session.get("client_addr"),
            session.get("state"),
            session.get("wait_event_type"),
            session.get("wait_event"),
            session.get("backend_start"),
            session.get("query_start"),
            session.get("query"),
        )
    return sessions


def terminate_test_db_sessions(db_name: str) -> list[dict[str, Any]]:
    if not db_name.startswith("test_"):
        raise ValueError(f"Refusing to terminate sessions for non-test database: {db_name}")

    before = fetch_test_db_sessions(db_name)
    if not before:
        return []

    with _maintenance_cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
            """,
            [db_name],
        )

    logger.warning(
        "Terminated %d session(s) on database %s: %s",
        len(before),
        db_name,
        [
            {
                "pid": row.get("pid"),
                "application_name": row.get("application_name"),
                "state": row.get("state"),
                "query": row.get("query"),
            }
            for row in before
        ],
    )
    return before


def test_database_exists(db_name: str) -> bool:
    with _maintenance_cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            [db_name],
        )
        return cursor.fetchone() is not None
