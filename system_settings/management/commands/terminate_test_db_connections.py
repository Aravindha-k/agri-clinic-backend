"""Terminate PostgreSQL sessions for CI test databases (defense in depth)."""

from __future__ import annotations

import os
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from config.pg_test_diagnostics import (
    count_test_db_sessions,
    log_test_db_sessions,
    resolve_test_database_name,
    terminate_test_db_sessions,
)


def is_ci_or_test_environment() -> bool:
    if "test" in sys.argv:
        return True
    if os.getenv("GITHUB_ACTIONS", "").lower() in {"1", "true", "yes"}:
        return True
    if os.getenv("CI", "").lower() in {"1", "true", "yes"}:
        return True
    if os.getenv("CI_TEST_DATABASE_NAME", "").strip():
        return True
    return False


class Command(BaseCommand):
    help = (
        "Terminate PostgreSQL sessions for a test database. "
        "CI/test environments only; database name must start with test_."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=None,
            help="Test database name (defaults to configured Django test DB name).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report matching sessions without terminating them.",
        )

    def handle(self, *args, **options):
        if not is_ci_or_test_environment():
            raise CommandError(
                "terminate_test_db_connections may only run in CI or during tests."
            )

        if connection.vendor != "postgresql":
            self.stdout.write("Not PostgreSQL; no sessions to terminate.")
            return

        db_name = resolve_test_database_name(options.get("database"))
        if not db_name.startswith("test_"):
            raise CommandError(
                f"Refusing to terminate connections for non-test database: {db_name}"
            )

        sessions = log_test_db_sessions(db_name, phase="terminate-command")
        if not sessions:
            self.stdout.write(f"No stale sessions for database {db_name}.")
            return

        if options.get("dry_run"):
            self.stdout.write(
                f"Would terminate {len(sessions)} session(s) for database {db_name}."
            )
            for session in sessions:
                self.stdout.write(
                    f"  pid={session.get('pid')} app={session.get('application_name')} "
                    f"state={session.get('state')} query={session.get('query')!r}"
                )
            return

        terminated = terminate_test_db_sessions(db_name)
        remaining = count_test_db_sessions(db_name)
        self.stdout.write(
            self.style.SUCCESS(
                f"Terminated {len(terminated)} session(s) for database {db_name}; "
                f"remaining={remaining}."
            )
        )
