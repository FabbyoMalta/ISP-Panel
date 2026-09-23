from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantModel


class AuditEntry(TenantModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
