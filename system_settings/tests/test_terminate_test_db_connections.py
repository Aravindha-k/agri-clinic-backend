"""Tests for CI PostgreSQL test database cleanup helpers."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from config.pg_test_diagnostics import resolve_test_database_name, sanitize_pg_identifier


class TerminateTestDbHelpersTests(SimpleTestCase):
    def test_sanitize_pg_identifier(self):
        self.assertEqual(
            sanitize_pg_identifier("test_agri_test_123_2"),
            "test_agri_test_123_2",
        )
        self.assertEqual(
            sanitize_pg_identifier("test-agri!test@run"),
            "test_agri_test_run",
        )

    @override_settings(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "agri_test",
                "TEST": {"NAME": "test_agri_test_99_1"},
            }
        }
    )
    def test_resolve_test_database_name_from_test_settings(self):
        self.assertEqual(
            resolve_test_database_name(),
            "test_agri_test_99_1",
        )

    @override_settings(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "agri_test",
            }
        }
    )
    def test_resolve_test_database_name_from_base_name(self):
        self.assertEqual(resolve_test_database_name(), "test_agri_test")
