#!/usr/bin/env bash
# Run the backend test suite in CI and local Linux environments.
# Uses explicit labels to avoid accidental discovery of scripts/ or conflicting modules.
set -Eeuo pipefail

if [[ -n "${GITHUB_RUN_ID:-}" && -z "${CI_TEST_DATABASE_NAME:-}" ]]; then
  export CI_TEST_DATABASE_NAME="test_agri_test_${GITHUB_RUN_ID}_${GITHUB_RUN_ATTEMPT:-1}"
fi

echo "CI test database name: ${CI_TEST_DATABASE_NAME:-<django default>}"
echo "Starting backend test suite (single Python process)..."

python manage.py test \
  config.tests \
  utils.tests \
  visits.tests \
  tracking.tests \
  mobile_api.tests \
  accounts.test_admin_security \
  farmers.tests \
  masters.tests.test_problem_master_list \
  masters.tests.test_problem_item_import \
  masters.tests.test_problem_category_cleanup \
  masters.tests.test_business_phase1 \
  masters.tests.test_location_masters \
  masters.tests.test_resolve_backfill_review \
  system_settings.tests.test_clean_test_data \
  system_settings.tests.test_terminate_test_db_connections \
  "$@"
TEST_EXIT=$?

echo "=== Process diagnostics after test run ==="
ps -ef | grep -E "python|manage.py|celery|pytest" | grep -v grep || true

exit "$TEST_EXIT"
