"""CI-hardened Django test runner for PostgreSQL teardown."""

from __future__ import annotations

import logging
import os
import time

from django.db import connections
from django.test.runner import DiscoverRunner

from config.pg_test_diagnostics import (
    count_test_db_sessions,
    log_test_db_sessions,
    resolve_test_database_name,
    terminate_test_db_sessions,
    test_database_exists,
)

logger = logging.getLogger(__name__)


class CIPostgresTestRunner(DiscoverRunner):
    """Close leaked connections, log pg_stat_activity, and terminate stale sessions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configured_test_db_name = resolve_test_database_name()

    def setup_databases(self, **kwargs):
        connections.close_all()
        logger.info(
            "CI configured test database name: %s",
            self._configured_test_db_name,
        )
        log_test_db_sessions(self._configured_test_db_name, phase="pre-setup")
        if self._should_manage_sessions():
            terminate_test_db_sessions(self._configured_test_db_name)
        return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        db_name = self._configured_test_db_name
        connections.close_all()
        time.sleep(0.25)
        connections.close_all()

        log_test_db_sessions(db_name, phase="pre-teardown-before-terminate")
        if self._should_manage_sessions():
            terminate_test_db_sessions(db_name)
            connections.close_all()
            time.sleep(0.25)
            remaining = count_test_db_sessions(db_name)
            log_test_db_sessions(db_name, phase="pre-teardown-after-terminate")
            if remaining:
                logger.error(
                    "%d session(s) still connected to %s immediately before DROP DATABASE",
                    remaining,
                    db_name,
                )

        super().teardown_databases(old_config, **kwargs)
        connections.close_all()

        if self._should_manage_sessions():
            remaining = count_test_db_sessions(db_name)
            exists = test_database_exists(db_name)
            logger.info(
                "Post-teardown database=%s exists=%s remaining_sessions=%d",
                db_name,
                exists,
                remaining,
            )

    def _should_manage_sessions(self) -> bool:
        if os.getenv("CI", "").lower() in {"1", "true", "yes"}:
            return True
        if os.getenv("GITHUB_ACTIONS", "").lower() in {"1", "true", "yes"}:
            return True
        return bool(os.getenv("CI_TEST_DATABASE_NAME", "").strip())
