from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from visits.models import Visit
from visits.farmer_sync import sync_visit_farmer_master

_syncing = False


def _invalidate_after_visit_change():
    try:
        from dashboard.services import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    except Exception:
        pass
    try:
        from farmers.services import invalidate_farmers_list_cache

        invalidate_farmers_list_cache()
    except Exception:
        pass


@receiver(post_save, sender=Visit)
def visit_post_save_sync_farmer(sender, instance, raw=False, **kwargs):
    if raw:
        return
    global _syncing
    if _syncing:
        return
    _syncing = True
    try:
        sync_visit_farmer_master(instance)
    finally:
        _syncing = False
    _invalidate_after_visit_change()


@receiver(post_delete, sender=Visit)
def visit_post_delete_invalidate(sender, instance, **kwargs):
    _invalidate_after_visit_change()
