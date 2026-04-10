from .models import AuditLog


from django.utils import timezone


def create_audit_log(
    actor, module, action, description, request=None, object_id=None, metadata=None
):
    """
    Central audit log utility. Safe for use in production/testing.
    - actor: User instance
    - module: str
    - action: str
    - description: str
    - request: Django request (optional, for IP)
    - object_id: str/int (optional)
    - metadata: dict (optional)
    """
    try:
        ip_address = None
        if request is not None:
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            if xff:
                ip_address = xff.split(",")[0].strip()
            else:
                ip_address = request.META.get("REMOTE_ADDR")
        AuditLog.objects.create(
            actor=actor,
            module=module,
            action=action,
            object_id=str(object_id) if object_id else None,
            description=description,
            metadata=metadata or {},
            ip_address=ip_address,
        )
    except Exception:
        pass
