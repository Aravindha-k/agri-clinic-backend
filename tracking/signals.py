"""Persist visit/farmer locations as permanent route stops.

Phase 5: Visit route-point creation is owned by
``visits.services.field_visit_service.ensure_visit_route_point``.
This signal is a compatibility safety net only — it never creates a second
point when the service already wrote one, and prefers the service helper.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from tracking.models import EmployeeRoutePoint
from visits.models import Visit
from visits.submitted import visit_has_submitted_details


@receiver(post_save, sender=Visit)
def visit_save_permanent_route_point(sender, instance: Visit, raw=False, **kwargs):
    if raw:
        return
    if not visit_has_submitted_details(instance):
        return
    if instance.latitude is None or instance.longitude is None:
        return
    if not instance.employee_id:
        return

    # Compatibility only: if a VISIT point already exists, do nothing.
    if EmployeeRoutePoint.objects.filter(
        visit_id=instance.id,
        point_type=EmployeeRoutePoint.POINT_VISIT,
    ).exists():
        return

    # Prefer canonical service (idempotent). Avoid legacy save_permanent_place_point.
    from visits.services.field_visit_service import ensure_visit_route_point

    ensure_visit_route_point(instance)
