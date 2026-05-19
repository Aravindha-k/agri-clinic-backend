from django.db.models.signals import post_save
from django.dispatch import receiver

from masters.models import Farmer, CropIssue, Recommendation, FarmerActivity
from visits.models import Visit


@receiver(post_save, sender=Farmer)
def log_farmer_created(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        FarmerActivity.objects.create(
            farmer=instance,
            activity_type="FARMER_CREATED",
            reference_id=instance.pk,
            created_by=instance.created_by_employee,
            notes=f"Farmer {instance.name} registered.",
        )


@receiver(post_save, sender=Visit)
def log_visit_activity(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    farmer = instance.farmer
    if not farmer and instance.farmer_phone:
        farmer = Farmer.objects.filter(phone=instance.farmer_phone).order_by("id").first()
    if not farmer:
        return

    label = instance.farmer_name or farmer.name
    if created:
        FarmerActivity.objects.create(
            farmer=farmer,
            activity_type="FOLLOWUP_VISIT",
            reference_id=instance.pk,
            created_by=instance.employee,
            notes=instance.notes or f"Visit logged for {label}",
        )
    else:
        from visits.submitted import visit_has_submitted_details

        if visit_has_submitted_details(instance):
            FarmerActivity.objects.get_or_create(
                farmer=farmer,
                activity_type="VISIT_COMPLETED",
                reference_id=instance.pk,
                defaults={
                    "created_by": instance.employee,
                    "notes": instance.notes or f"Visit recorded for {label}",
                },
            )


@receiver(post_save, sender=CropIssue)
def log_issue_reported(sender, instance, created, **kwargs):
    if created and instance.visit_id:
        visit = instance.visit
        if visit.farmer_name:
            FarmerActivity.objects.create(
                activity_type="ISSUE_REPORTED",
                reference_id=instance.pk,
                notes=instance.description or f"Issue for {visit.farmer_name}",
            )


@receiver(post_save, sender=Recommendation)
def log_recommendation_given(sender, instance, created, **kwargs):
    if created and instance.issue_id:
        issue = instance.issue
        if issue.visit_id and issue.visit.farmer_name:
            FarmerActivity.objects.create(
                activity_type="RECOMMENDATION_GIVEN",
                reference_id=instance.pk,
                created_by=instance.given_by,
                notes=instance.notes or f"Recommendation for {issue.visit.farmer_name}",
            )
