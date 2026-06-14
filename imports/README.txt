Place quarter group-summary Excel files here:

  QUARTER 1GrpSum.xlsx
  QUARTER 2GrpSum.xlsx
  QUARTER 3GrpSum.xlsx
  QUARTER 4GrpSum.xlsx

Initial live import (deletes old farmer data first):

  python manage.py debug_farmer_environment
  python manage.py clean_and_import_farmers --confirm

Merge additional quarters into existing farmers (no delete):

  python manage.py import_farmers_quarters --merge --dry-run
  python manage.py import_farmers_quarters --merge --confirm

Default paths are used when quarter file flags are omitted.
