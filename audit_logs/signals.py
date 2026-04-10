from django.db.models.signals import post_save
from django.dispatch import receiver
from visits.models import Visit
from accounts.models import EmployeeProfile
from masters.models import Farmer
from tracking.models import WorkDay
from django.contrib.auth import get_user_model
from audit_logs.utils import create_audit_log

User = get_user_model()


# VISIT CREATE
@receiver(post_save, sender=Visit)
def log_visit_create(sender, instance, created, **kwargs):
    if created:
        try:
            create_audit_log(
                actor=instance.employee,
                module="VISITS",
                action="CREATE",
                description=f"Visit created for farmer {instance.farmer_name}",
            )
        except Exception:
            pass


# EMPLOYEE CREATE/UPDATE
@receiver(post_save, sender=EmployeeProfile)
def log_employee_create_update(sender, instance, created, **kwargs):
    try:
        action = "CREATE" if created else "UPDATE"
        create_audit_log(
            actor=instance.user,
            module="EMPLOYEES",
            action=action,
            description=f"Employee {action.lower()}d: {instance.user.username}",
        )
    except Exception:
        pass


# FARMER CREATE/UPDATE
@receiver(post_save, sender=Farmer)
def log_farmer_create_update(sender, instance, created, **kwargs):
    try:
        action = "CREATE" if created else "UPDATE"
        create_audit_log(
            actor=instance.created_by,
            module="FARMERS",
            action=action,
            description=f"Farmer {action.lower()}d: {instance.name}",
        )
    except Exception:
        pass


# WORKDAY START/END
@receiver(post_save, sender=WorkDay)
def log_workday_start_end(sender, instance, created, **kwargs):
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
