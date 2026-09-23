from .models import AuditEntry


def record(actor, action, obj, changes=None):
    return AuditEntry.objects.create(
        tenant_id=obj.tenant_id,
        actor=actor,
        action=action,
        object_type=obj._meta.label_lower,
        object_id=str(obj.pk),
        changes=changes or {},
    )
