"""Pulls a per-tenant summary from NetBackup (device counts, backup health,
POP estimate) and records it as MetricObservation history for each mapped
tenant. Meant to be invoked by an external cron/systemd timer (this
project has no worker/queue infra — see docs/architecture.md) — recommended
daily, since idempotency in apps.integrations.services is bucketed by
calendar day.

Thin wrapper around apps.integrations.services — the actual per-tenant
write logic is shared with apps.portal.views.netbackup_import (the
"vincular tenant" screen, which calls services.sync_mapping() for a
single just-created mapping right away rather than waiting for this
command's next run).

Never wraps the mapping loop in an outer @transaction.atomic: each
`with tenant_context(...)` inside services.sync_mapping() is already its
own transaction, which is what gives per-tenant atomicity and lets one
tenant's failure never roll back a sibling tenant's already-committed
writes, or this command's own IntegrationRun row.
"""

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations import services
from apps.integrations.models import ExternalObjectMapping, IntegrationRun


class Command(BaseCommand):
    help = "Sincroniza contagens de equipamentos/backup do NetBackup para MetricObservation."

    def handle(self, *args, **options):
        if not settings.NETBACKUP_API_URL or not settings.NETBACKUP_API_TOKEN:
            self.stdout.write(
                self.style.WARNING(
                    "NETBACKUP_API_URL/NETBACKUP_API_TOKEN não configurados; ignorando."
                )
            )
            return

        actor = services.ensure_sync_actor()
        run = IntegrationRun.objects.create(system="netbackup")

        mappings = list(
            ExternalObjectMapping.objects.filter(system="netbackup").select_related("tenant")
        )
        run.tenants_considered = len(mappings)
        if not mappings:
            run.status = IntegrationRun.Status.SUCCESS
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "finished_at", "tenants_considered"])
            self.stdout.write(self.style.SUCCESS("Nenhum ExternalObjectMapping cadastrado."))
            return

        try:
            payload = services.fetch_netbackup_summary()
        except (httpx.HTTPError, ValueError) as exc:
            run.status = IntegrationRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error = str(exc)[:2000]
            run.save(update_fields=["status", "finished_at", "error", "tenants_considered"])
            self.stderr.write(self.style.ERROR(f"Falha ao consultar o NetBackup: {exc}"))
            return

        details: list[dict] = []
        succeeded = 0
        failed = 0

        for mapping in mappings:
            entry = services.sync_mapping(actor, mapping, payload)
            details.append(entry)
            if entry["outcome"] == "ok":
                succeeded += 1
            else:
                failed += 1

        run.tenants_matched = sum(1 for d in details if d["outcome"] != "not_found_in_netbackup")
        run.tenants_succeeded = succeeded
        run.tenants_failed = failed
        if failed == 0:
            run.status = IntegrationRun.Status.SUCCESS
        elif succeeded == 0:
            run.status = IntegrationRun.Status.FAILED
        else:
            run.status = IntegrationRun.Status.PARTIAL_FAILURE
        run.finished_at = timezone.now()
        run.details = details
        run.save(
            update_fields=[
                "tenants_matched",
                "tenants_succeeded",
                "tenants_failed",
                "status",
                "finished_at",
                "details",
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sincronização concluída: {succeeded} ok, {failed} falha(s) de "
                f"{len(mappings)} mapeamento(s)."
            )
        )
