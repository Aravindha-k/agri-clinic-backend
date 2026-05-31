from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from visits.models import Visit
from accounts.models import EmployeeProfile
from masters.models import Farmer
from tracking.models import WorkDay
from django.contrib.auth import get_user_model
from audit_logs.utils import create_audit_log

User = get_user_model()


# VISIT CREATE / UPDATE
@receiver(post_save, sender=Visit)
def log_visit_create_update(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        action = "CREATE" if created else "UPDATE"
        create_audit_log(
            actor=instance.employee,
            module="VISITS",
            action=action,
            object_id=instance.pk,
            description=f"Visit {action.lower()} for farmer {instance.farmer_name or instance.farmer_id}",
        )
    except Exception:
        pass


@receiver(post_delete, sender=Visit)
def log_visit_delete(sender, instance, **kwargs):
    try:
        create_audit_log(
            actor=instance.employee,
            module="VISITS",
            action="DELETE",
            object_id=instance.pk,
            description=f"Visit deleted for farmer {instance.farmer_name or instance.farmer_id}",
        )
    except Exception:
        pass


# EMPLOYEE CREATE/UPDATE
@receiver(post_save, sender=EmployeeProfile)
def log_employee_create_update(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        action = "CREATE" if created else "UPDATE"
        create_audit_log(
            actor=instance.user,
            module="EMPLOYEES",
            action=action,
            object_id=instance.pk,
            description=f"Employee {action.lower()}d: {instance.user.username}",
        )
    except Exception:
        pass


# FARMER CREATE/UPDATE
@receiver(post_save, sender=Farmer)
def log_farmer_create_update(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        action = "CREATE" if created else "UPDATE"
        actor = instance.created_by_employee
        if actor is None and instance.assigned_employee_id:
            actor = instance.assigned_employee
        create_audit_log(
            actor=actor,
            module="FARMERS",
            action=action,
            object_id=instance.pk,
            description=f"Farmer {action.lower()}d: {instance.name}",
        )
    except Exception:
        pass


# WORKDAY START/END
@receiver(post_save, sender=WorkDay)
def log_workday_start_end(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        action = "START" if created and instance.is_active else "END"
        if action == "START" or (not created and not instance.is_active):
            create_audit_log(
                actor=instance.user,
                module="WORKDAY",
                action=action,
                description=f"Workday {action.lower()}ed for {instance.user.username}",
            )
    except Exception:
        pass
