"""
Visit status groupings for KPIs and dashboards.

Canonical choices on Visit are pending / active / completed (see Visit.STATUS_CHOICES).
Legacy rows may still store "scheduled" (older migrations) or "verified" (older choices).
"""

PENDING_STATUSES = ("pending", "scheduled")
COMPLETED_STATUSES = ("completed", "verified")
ACTIVE_STATUS = "active"
