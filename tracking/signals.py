"""Persist visit/farmer locations as permanent route stops."""

from datetime import datetime

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from tracking.duty_service import save_permanent_place_point
from tracking.employee_report import attach_visit_duty_links
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

    recorded_at = timezone.now()
    if instance.visit_date and instance.visit_time:
        recorded_at = timezone.make_aware(
            datetime.combine(instance.visit_date, instance.visit_time)
        )

    if EmployeeRoutePoint.objects.filter(
        visit_id=instance.id,
        point_type=EmployeeRoutePoint.POINT_VISIT,
    ).exists():
        return

    save_permanent_place_point(
        user=instance.employee,
        duty_session=None,
        latitude=float(instance.latitude),
        longitude=float(instance.longitude),
        recorded_at=recorded_at,
        point_type=EmployeeRoutePoint.POINT_VISIT,
        visit_id=instance.id,
        farmer_id=instance.farmer_id,
    )
    attach_visit_duty_links(instance)
