"""Visit status helpers for employee-completed flow."""

from visits.kpi_status import COMPLETED_STATUSES

# Employee mobile submit always stores this status.
EMPLOYEE_SUBMIT_STATUS = "completed"

# Admin product list: completed field visits only (incl. legacy verified).
ADMIN_LIST_STATUSES = COMPLETED_STATUSES
