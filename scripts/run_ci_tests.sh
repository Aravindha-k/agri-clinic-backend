#!/usr/bin/env bash
# Run the backend test suite in CI and local Linux environments.
# Uses explicit labels to avoid accidental discovery of scripts/ or conflicting modules.
set -Eeuo pipefail

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
  system_settings.tests.test_clean_test_data \
  "$@"
