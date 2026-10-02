"""Infrastructure/config models for pulling external-system data into this
portal — see docs/architecture.md "Evolução" (Fase 2) and
apps.integrations.management.commands.sync_netbackup.

Deliberately NOT `TenantModel`: `ScopedManager.get_queryset()`
(apps.tenancy.models) returns `.none()` without an active tenant context,
and `TenantModel.save()` requires `tenant_id == current_tenant.get()`. The
sync job's first step — listing every mapping across every tenant, before
entering any one tenant's `tenant_context()` — is a query shape a
TenantModel cannot express. These sit at the same level as `Tenant`/
`TenantMembership` themselves, not as a tenant's own business data.

No `Integration` catalog model: `system` is a plain string constant
(`"netbackup"`) rather than a FK to a config-row table, since there is
exactly one external system today — see `NETBACKUP_API_URL`/
`NETBACKUP_API_TOKEN` in settings for where its own config actually lives.
"""

import uuid

from django.db import models


class IntegrationRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Em execução"
        SUCCESS = "success", "Sucesso"
        PARTIAL_FAILURE = "partial_failure", "Falha parcial"
        FAILED = "failed", "Falha"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    system = models.CharField(max_length=40, default="netbackup")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    tenants_considered = models.PositiveIntegerField(default=0)
    tenants_matched = models.PositiveIntegerField(default=0)
    tenants_succeeded = models.PositiveIntegerField(default=0)
    tenants_failed = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    # Per-tenant outcome dicts — includes the raw upstream timestamp(s) that
    # don't fit a Decimal MetricObservation.value, kept here for inspection.
    details = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.system} @ {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class ExternalObjectMapping(models.Model):
    """Links a portal Tenant to its identifier in an external system (e.g.
    the NetBackup tenant slug). Created manually via /admin/ — the sync job
    never auto-creates a mapping, so linking a client is always a deliberate
    action.

    This table's `tenant` FK (column `tenant_id`) is explicitly exempted
    from the RLS-presence check in
    apps.portal.management.commands.check_runtime_db — same reasoning as
    that command's existing `tenancy_tenantmembership` exemption: it must
    be listable across every tenant before any one tenant's context is
    active (the sync job's first step), so it cannot carry RLS the way a
    tenant's own business data does.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    system = models.CharField(max_length=40, default="netbackup")
    external_id = models.CharField("Identificador externo", max_length=200)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["system", "external_id"], name="unique_external_mapping"
            ),
            models.UniqueConstraint(
                fields=["system", "tenant"], name="one_mapping_per_system_per_tenant"
            ),
        ]

    def __str__(self):
        return f"{self.system}:{self.external_id} -> {self.tenant}"
